mod credentials;
mod handlers;
mod models;
mod proxy;

use models::ActionCommand;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::ClientConfig;
use sqlx::postgres::PgPoolOptions;
use std::time::Duration;
use tracing::{error, info, warn};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env()
            .add_directive("execution_engine=info".parse().unwrap())
            .add_directive("rdkafka=warn".parse().unwrap()))
        .init();
    info!("Omni SOTA Execution Engine (The Muscle) v0.2 starting…");

    let brokers = std::env::var("KAFKA_BROKERS").unwrap_or_else(|_| "localhost:9092".to_string());

    // Idempotency ledger pool — INSERT … ON CONFLICT DO NOTHING is the only
    // SQL the muscle runs against Postgres. Everything else flows through
    // ActionCommand.payload (rendered upstream) or the credential redemption
    // endpoint. No content drift between Rust and the live schema.
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
                info!("connected to Postgres for processed_commands ledger");
                Some(p)
            }
            Err(e) => {
                warn!("Postgres connect failed ({}) — idempotency ledger disabled", e);
                None
            }
        }
    };

    let consumer: StreamConsumer = ClientConfig::new()
        .set("group.id", "execution-engine-v2")
        .set("bootstrap.servers", &brokers)
        .set("enable.partition.eof", "false")
        .set("session.timeout.ms", "6000")
        .set("enable.auto.commit", "false")
        .create()?;
    consumer.subscribe(&["outreach.commands"])?;

    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", &brokers)
        .set("message.timeout.ms", "5000")
        .create()?;

    info!("muscle ready — consuming outreach.commands");

    loop {
        match consumer.recv().await {
            Err(e) => error!("kafka error: {e}"),
            Ok(borrowed) => {
                let payload = match borrowed.payload() {
                    None => continue,
                    Some(b) => match std::str::from_utf8(b) {
                        Ok(s) => s,
                        Err(e) => {
                            error!("utf8 decode: {e}");
                            continue;
                        }
                    }
                };

                let command: ActionCommand = match serde_json::from_str(payload) {
                    Ok(c) => c,
                    Err(e) => {
                        error!("invalid ActionCommand JSON: {e}");
                        let _ = producer.send(
                            FutureRecord::to("outreach.dead_letter")
                                .payload(payload)
                                .key("schema_error"),
                            Duration::from_secs(5),
                        ).await;
                        let _ = consumer.commit_message(&borrowed, CommitMode::Async);
                        continue;
                    }
                };

                let command_id = command.command_id;
                info!("executing command {} channel={}", command_id, command.channel.as_str());

                if let Some(pool) = &db_pool {
                    let claim = sqlx::query(
                        "INSERT INTO processed_commands (command_id, channel, task_id, lead_id, status) \
                         VALUES ($1, $2, $3, $4, 'claimed') ON CONFLICT (command_id) DO NOTHING"
                    )
                    .bind(command_id)
                    .bind(command.channel.as_str())
                    .bind(command.task_id)
                    .bind(command.lead.id)
                    .execute(pool)
                    .await;
                    match claim {
                        Ok(res) if res.rows_affected() == 0 => {
                            warn!("duplicate command {command_id}; skipping");
                            consumer.commit_message(&borrowed, CommitMode::Async)?;
                            continue;
                        }
                        Err(e) => warn!("ledger insert failed for {command_id} ({e}); proceeding without dedupe guard"),
                        _ => {}
                    }
                }

                let result = handlers::dispatch(&command).await;

                if let Some(pool) = &db_pool {
                    let _ = sqlx::query(
                        "UPDATE processed_commands SET status=$1, processed_at=NOW() WHERE command_id=$2"
                    )
                    .bind(result.status.as_str())
                    .bind(command_id)
                    .execute(pool)
                    .await;
                }

                let result_json = serde_json::to_string(&result)?;
                if let Err((e, _)) = producer
                    .send(
                        FutureRecord::to("outreach.results")
                            .payload(&result_json)
                            .key(&command_id.to_string()),
                        Duration::from_secs(5),
                    )
                    .await
                {
                    error!("failed to publish result for {command_id}: {e}");
                }
                consumer.commit_message(&borrowed, CommitMode::Async)?;
                info!("result published for {command_id} status={}", result.status.as_str());
            }
        }
    }
}
