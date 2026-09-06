//! Native artifact commands share the authenticated local transport.

pub(crate) mod data_files;
pub(crate) mod diagnostics;

use crate::proxy::{forward, DesktopRequest};
use crate::runtime::RuntimeController;

fn fetch_json(controller: &RuntimeController, path: String) -> Result<serde_json::Value, String> {
    let (port, session) = controller.target()?;
    let response = forward(
        port,
        &session,
        DesktopRequest {
            path,
            method: "GET".to_string(),
            body: None,
        },
    )?;
    if response.status != 200 {
        return Err("The requested local artifact was rejected safely.".to_string());
    }
    serde_json::from_str(&response.body)
        .map_err(|_| "The requested local artifact could not be verified.".to_string())
}
