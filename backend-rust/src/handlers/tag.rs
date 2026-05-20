//! Tag mutations. The muscle emits a result with `lead_mutations.{tag_op}`;
//! the Python sync worker applies it to the leads table (array_append /
//! array_remove). No network call from Rust.

use crate::handlers::common;
use crate::models::{ActionCommand, ExecutionResult};
use serde_json::json;

pub async fn handle_add_tag(command: &ActionCommand) -> ExecutionResult {
    let tag = common::s(command, "tag");
    if tag.is_empty() {
        return common::fail(command, "tag missing", false);
    }
    common::ok(
        command,
        json!({"op": "add_tag", "tag": tag}),
        Some("tag_added"),
        json!({"add_tag": tag}),
    )
}

pub async fn handle_remove_tag(command: &ActionCommand) -> ExecutionResult {
    let tag = common::s(command, "tag");
    if tag.is_empty() {
        return common::fail(command, "tag missing", false);
    }
    common::ok(
        command,
        json!({"op": "remove_tag", "tag": tag}),
        Some("tag_removed"),
        json!({"remove_tag": tag}),
    )
}
