mod models;
mod handlers;
mod proxy;

use models::{ActionCommand};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::ClientConfig;
use std::time::Duration;
use tracing::{info, error};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt::init();
    info!("Omni SOTA Execution Engine (The Muscle) starting...");

    let brokers = std::env::var("KAFKA_BROKERS").unwrap_or_else(|_| "localhost:9092".to_string());
    
    // 1. Configure Kafka Consumer (Command Topic)
    let consumer: StreamConsumer = ClientConfig::new()
        .set("group.id", "execution-engine-v1")
        .set("bootstrap.servers", &brokers)
        .set("enable.partition.eof", "false")
        .set("session.timeout.ms", "6000")
        .set("enable.auto.commit", "true")
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
                let payload = match borrowed_message.payload::<str>() {
                    None => continue,
                    Some(Ok(s)) => s,
                    Some(Err(e)) => {
                        error!("Error deserializing message: {}", e);
                        continue;
                    }
                };

                let command: ActionCommand = match serde_json::from_str(payload) {
                    Ok(c) => c,
                    Err(e) => {
                        error!("Invalid JSON schema: {}", e);
                        continue;
                    }
                };
                
                let command_id = command.command_id;
                info!("Executing command {} for channel {:?}", command_id, command.channel);

                // 4. DISPATCH TO SOTA HANDLERS
                let mut result = handlers::dispatch(&command).await;
                result.metadata = command.metadata.clone(); // Mirror context for Flink

                // 5. Report Result back to the stream
                let result_json = serde_json::to_string(&result)?;
                let _ = producer.send(
                    FutureRecord::to("outreach.results")
                        .payload(&result_json)
                        .key(&command_id.to_string()),
                    Duration::from_secs(5),
                ).await.map_err(|(e, _)| e)?;
                
                info!("Result reported for command {}", command_id);
            }
        }
    }
}
