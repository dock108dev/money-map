use std::io::Read;
use std::time::Duration;

use reqwest::blocking::{Client, Response};
use reqwest::header::{CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_TYPE, ETAG, LAST_MODIFIED};
use reqwest::Method;
use serde::{Deserialize, Serialize};

pub const MAX_REQUEST_BODY: usize = 1_048_576;
pub const MAX_RESPONSE_BODY: usize = 8_388_608;
const MAX_PATH: usize = 4_096;

#[derive(Clone, Debug, Deserialize)]
pub struct DesktopRequest {
    pub path: String,
    pub method: String,
    pub body: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct DesktopHeader {
    pub name: String,
    pub value: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct DesktopResponse {
    pub status: u16,
    pub headers: Vec<DesktopHeader>,
    pub body: String,
}

#[derive(Clone, Copy)]
struct ProxyLimits {
    connect: Duration,
    read: Duration,
    total: Duration,
    max_response: usize,
}

impl Default for ProxyLimits {
    fn default() -> Self {
        Self {
            connect: Duration::from_secs(2),
            read: Duration::from_secs(10),
            total: Duration::from_secs(20),
            max_response: MAX_RESPONSE_BODY,
        }
    }
}

pub fn validate_request(request: &DesktopRequest) -> Result<Method, String> {
    validate_path(&request.path)?;
    let method = Method::from_bytes(request.method.to_ascii_uppercase().as_bytes())
        .map_err(|_| "The desktop request method was rejected.".to_string())?;
    if !matches!(
        method,
        Method::GET | Method::POST | Method::PUT | Method::DELETE
    ) {
        return Err("The desktop request method was rejected.".to_string());
    }
    if request.body.as_deref().unwrap_or_default().len() > MAX_REQUEST_BODY {
        return Err("The desktop request was too large.".to_string());
    }
    Ok(method)
}

pub fn validate_path(value: &str) -> Result<(), String> {
    if value.len() > MAX_PATH
        || !value.is_ascii()
        || !value.starts_with("/api/")
        || value.contains(['\r', '\n', '\\', '#'])
        || value.bytes().any(|byte| byte < 0x20 || byte == 0x7f)
    {
        return Err("The desktop request path was rejected.".to_string());
    }
    let path = value.split_once('?').map_or(value, |(path, _)| path);
    if path.contains("//")
        || path
            .split('/')
            .skip(2)
            .any(|segment| segment.is_empty() || segment == "." || segment == "..")
    {
        return Err("The desktop request path was rejected.".to_string());
    }
    let bytes = value.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] != b'%' {
            index += 1;
            continue;
        }
        if index + 2 >= bytes.len()
            || !bytes[index + 1].is_ascii_hexdigit()
            || !bytes[index + 2].is_ascii_hexdigit()
        {
            return Err("The desktop request path was rejected.".to_string());
        }
        let encoded = value[index + 1..index + 3].to_ascii_lowercase();
        if matches!(encoded.as_str(), "0a" | "0d" | "2e" | "2f" | "5c") {
            return Err("The desktop request path was rejected.".to_string());
        }
        index += 3;
    }
    Ok(())
}

pub fn health_ready(port: u16, session: &str) -> bool {
    let limits = ProxyLimits {
        connect: Duration::from_millis(250),
        read: Duration::from_millis(500),
        total: Duration::from_millis(750),
        max_response: 64 * 1024,
    };
    let request = DesktopRequest {
        path: "/api/desktop/health".to_string(),
        method: "GET".to_string(),
        body: None,
    };
    forward_with_limits(port, session, request, limits)
        .map(|response| response.status == 200 && response.body.contains("\"ready\":true"))
        .unwrap_or(false)
}

pub fn forward(
    port: u16,
    session: &str,
    request: DesktopRequest,
) -> Result<DesktopResponse, String> {
    forward_with_limits(port, session, request, ProxyLimits::default())
}

fn forward_with_limits(
    port: u16,
    session: &str,
    request: DesktopRequest,
    limits: ProxyLimits,
) -> Result<DesktopResponse, String> {
    let method = validate_request(&request)?;
    let client = Client::builder()
        .connect_timeout(limits.connect)
        .timeout(limits.total.min(limits.read))
        .build()
        .map_err(|_| "The local service request could not be prepared.".to_string())?;
    let mut builder = client
        .request(method, format!("http://127.0.0.1:{port}{}", request.path))
        .header("Host", format!("127.0.0.1:{port}"))
        .header("X-Money-Map-Session", session)
        .header(CONTENT_TYPE, "application/json")
        .header(CACHE_CONTROL, "no-store");
    if let Some(body) = request.body {
        builder = builder.body(body);
    }
    let response = builder
        .send()
        .map_err(|_| "The local service is unavailable.".to_string())?;
    bounded_response(response, limits.max_response)
}

fn bounded_response(mut response: Response, maximum: usize) -> Result<DesktopResponse, String> {
    let status = response.status().as_u16();
    let headers = [CONTENT_TYPE, CONTENT_DISPOSITION, ETAG, LAST_MODIFIED]
        .into_iter()
        .filter_map(|name| {
            response.headers().get(&name).and_then(|value| {
                value.to_str().ok().map(|value| DesktopHeader {
                    name: name.as_str().to_string(),
                    value: value.to_string(),
                })
            })
        })
        .chain(std::iter::once(DesktopHeader {
            name: CACHE_CONTROL.as_str().to_string(),
            value: "no-store".to_string(),
        }))
        .collect();
    let mut body = Vec::with_capacity(maximum.min(64 * 1024));
    response
        .by_ref()
        .take((maximum + 1) as u64)
        .read_to_end(&mut body)
        .map_err(|_| "The local service response failed.".to_string())?;
    if body.len() > maximum {
        return Err("The local service response was too large.".to_string());
    }
    let body = String::from_utf8(body)
        .map_err(|_| "The local service returned unsupported content.".to_string())?;
    Ok(DesktopResponse {
        status,
        headers,
        body,
    })
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;
    use std::time::Duration;

    use super::{forward_with_limits, validate_request, DesktopRequest, ProxyLimits};

    fn request(path: &str, method: &str, body: Option<String>) -> DesktopRequest {
        DesktopRequest {
            path: path.to_string(),
            method: method.to_string(),
            body,
        }
    }

    #[test]
    fn paths_methods_and_request_sizes_are_bounded() {
        for path in [
            "/",
            "/api/../private",
            "/api/%2e%2e/private",
            "/api//health",
            "/api/health\nInjected: yes",
            "http://example.invalid/api/health",
            "/api/health\\private",
        ] {
            assert!(
                validate_request(&request(path, "GET", None)).is_err(),
                "{path}"
            );
        }
        for method in ["PATCH", "OPTIONS", "TRACE", "CONNECT"] {
            assert!(validate_request(&request("/api/health", method, None)).is_err());
        }
        assert!(validate_request(&request("/api/health?period=all", "GET", None)).is_ok());
        assert!(validate_request(&request(
            "/api/write",
            "POST",
            Some("x".repeat(super::MAX_REQUEST_BODY + 1))
        ))
        .is_err());
    }

    fn serve_once(response: &'static [u8]) -> u16 {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 4096];
            let _ = stream.read(&mut request);
            stream.write_all(response).unwrap();
        });
        port
    }

    #[test]
    fn chunked_response_is_decoded_and_safe_headers_are_preserved() {
        let port = serve_once(
            b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n7\r\n{\"ok\":1\r\n1\r\n}\r\n0\r\n\r\n",
        );
        let response = forward_with_limits(
            port,
            "synthetic-session",
            request("/api/test", "POST", Some("{}".to_string())),
            ProxyLimits::default(),
        )
        .unwrap();
        assert_eq!(response.status, 201);
        assert_eq!(response.body, "{\"ok\":1}");
        assert!(response
            .headers
            .iter()
            .any(|header| header.name == "content-type"));
        assert!(response
            .headers
            .iter()
            .any(|header| header.name == "cache-control" && header.value == "no-store"));
        assert!(!response
            .headers
            .iter()
            .any(|header| header.name == "connection"));
    }

    #[test]
    fn response_size_and_timeouts_map_to_sanitized_failures() {
        let port = serve_once(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n12345");
        let result = forward_with_limits(
            port,
            "private-session-value",
            request("/api/test", "GET", None),
            ProxyLimits {
                max_response: 4,
                ..ProxyLimits::default()
            },
        );
        assert_eq!(
            result.unwrap_err(),
            "The local service response was too large."
        );

        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            let (_stream, _) = listener.accept().unwrap();
            thread::sleep(Duration::from_millis(200));
        });
        let error = forward_with_limits(
            port,
            "private-session-value",
            request("/api/test", "GET", None),
            ProxyLimits {
                connect: Duration::from_millis(20),
                read: Duration::from_millis(20),
                total: Duration::from_millis(40),
                max_response: 1024,
            },
        )
        .unwrap_err();
        assert!(!error.contains("private-session-value"));
        assert!(!error.contains(&port.to_string()));
    }
}
