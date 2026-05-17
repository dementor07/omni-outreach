mod models;
mod handlers;
mod proxy;

use models::ActionCommand;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::message::Message;
use rdkafka::ClientConfig;
use sqlx::postgres::PgPoolOptions;
use std::time::Duration;
use tracing::{info, warn, error};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();
    info!("Omni SOTA Execution Engine (The Muscle) starting...");

    let brokers = std::env::var("KAFKA_BROKERS").unwrap_or_else(|_| "localhost:9092".to_string());

    // 0. Postgres pool — used only for the idempotency ledger (processed_commands).
    // We accept missing/invalid DSN as a soft failure: warn loudly and run without dedupe
    // rather than refuse to consume. This matches existing failure semantics in the engine.
    let dsn = std::env::var("DATABASE_URL").unwrap_or_default();
    let db_pool = if dsn.is_empty() {
        warn!("DATABASE_URL not set — idempotency ledger disabled; commands may double-send on Kafka redelivery");
        None
    } else {
        match PgPoolOptions::new()
            .max_connections(4)
            .acquire_timeout(Duration::from_secs(5))
            .connect(&dsn)
            .await
        {
            Ok(p) => {
                info!("Connected to Postgres for processed_commands ledger");
                Some(p)
            }
            Err(e) => {
                warn!("Postgres connect failed ({}) — idempotency ledger disabled", e);
                None
            }
        }
    };

    // 1. Configure Kafka Consumer (Command Topic)
    let consumer: StreamConsumer = ClientConfig::new()
        .set("group.id", "execution-engine-v1")
        .set("bootstrap.servers", &brokers)
        .set("enable.partition.eof", "false")
        .set("session.timeout.ms", "6000")
        .set("enable.auto.commit", "false")
        .create()?;

    consumer.subscribe(&["outreach.commands"])?;

    // 2. Configure Kafka Producer (Result Topic)
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", &brokers)
        .set("message.timeout.ms", "5000")
        .create()?;

    info!("Connected to Redpanda. Muscle is ready for action.");

    // 3. The Execution Loop
    loop {
        match consumer.recv().await {
            Err(e) => error!("Kafka error: {}", e),
            Ok(borrowed_message) => {
                let payload = match borrowed_message.payload() {
                    None => continue,
                    Some(b) => match std::str::from_utf8(b) {
                        Ok(s) => s,
                        Err(e) => {
                            error!("Error decoding UTF-8: {}", e);
                            continue;
                        }
                    }
                };

                let command: ActionCommand = match serde_json::from_str(payload) {
                    Ok(c) => c,
                    Err(e) => {
                        error!("Invalid JSON schema: {}", e);
                        let _ = producer.send(
                            FutureRecord::to("outreach.dead_letter")
                                .payload(payload)
                                .key(b"schema_error"),
                            Duration::from_secs(5),
                        ).await;
                        let _ = consumer.commit_message(&borrowed_message, CommitMode::Async);
                        continue;
                    }
                };
                
                let command_id = command.command_id;
                info!("Executing command {} for channel {:?}", command_id, command.channel);

                // 3b. Idempotency claim — atomic INSERT ON CONFLICT DO NOTHING. If we
                // can't insert, this command_id was already processed (Kafka redelivery
                // after a crash between handler success and commit_message). Skip the
                // side-effect handler entirely and just commit the offset.
                if let Some(pool) = &db_pool {
                    let channel_str = format!("{:?}", command.channel).to_lowercase();
                    let claim = sqlx::query(
                        "INSERT INTO processed_commands (command_id, channel, task_id, lead_id, status) \
                         VALUES ($1, $2, $3, $4, 'claimed') ON CONFLICT (command_id) DO NOTHING"
                    )
                    .bind(command_id)
                    .bind(&channel_str)
                    .bind(command.task_id)
                    .bind(command.lead.id)
                    .execute(pool)
                    .await;

                    match claim {
                        Ok(res) if res.rows_affected() == 0 => {
                            warn!("Skipping duplicate command {} (already in processed_commands)", command_id);
                            consumer.commit_message(&borrowed_message, CommitMode::Async)?;
                            continue;
                        }
                        Err(e) => {
                            warn!("Ledger insert failed for {} ({}) — proceeding without dedupe guard", command_id, e);
                        }
                        _ => {}
                    }
                }

                // 4. DISPATCH TO SOTA HANDLERS
                let mut result = handlers::dispatch(&command).await;
                result.metadata = command.metadata.clone(); // Mirror context for Flink

                // 4b. Finalize ledger row with terminal status (best-effort).
                if let Some(pool) = &db_pool {
                    let status_str = format!("{:?}", result.status).to_lowercase();
                    let _ = sqlx::query(
                        "UPDATE processed_commands SET status=$1, processed_at=NOW() WHERE command_id=$2"
                    )
                    .bind(&status_str)
                    .bind(command_id)
                    .execute(pool)
                    .await;
                }

                // 5. Report Result back to the stream
                let result_json = serde_json::to_string(&result)?;
                let _ = producer.send(
                    FutureRecord::to("outreach.results")
                        .payload(&result_json)
                        .key(&command_id.to_string()),
                    Duration::from_secs(5),
                ).await.map_err(|(e, _)| e)?;
                consumer.commit_message(&borrowed_message, CommitMode::Async)?;
                
                info!("Result reported for command {}", command_id);
            }
        }
    }
}
