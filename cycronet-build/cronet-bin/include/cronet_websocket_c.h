// Copyright 2024 The Chromium Authors
// Use of this source code is govddderned by a BSD-style license that can be
// found in the LICENSE file.

#ifndef COMPONENTS_CRONET_NATIVE_INCLUDE_CRONET_WEBSOCKET_C_H_
#define COMPONENTS_CRONET_NATIVE_INCLUDE_CRONET_WEBSOCKET_C_H_

#include "cronet_export.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct Cronet_Engine Cronet_Engine;
typedef Cronet_Engine* Cronet_EnginePtr;
typedef struct Cronet_WebSocket* Cronet_WebSocketPtr;

typedef enum {
  Cronet_WebSocket_MESSAGE_TEXT = 1,
  Cronet_WebSocket_MESSAGE_BINARY = 2,
} Cronet_WebSocket_MessageType;

typedef struct {
  // Called when the WebSocket connection is established.
  // |protocol| is the negotiated sub-protocol (may be empty).
  void (*on_open)(Cronet_WebSocketPtr ws, void* user_data,
                  const char* protocol);

  // Called when a complete message is received.
  // |data|/|len| is the payload. For TEXT, data is valid UTF-8.
  void (*on_message)(Cronet_WebSocketPtr ws, void* user_data,
                     Cronet_WebSocket_MessageType type,
                     const void* data, uint64_t len);

  // Called when the connection is closed.
  // |was_clean| is 1 if the close handshake completed normally.
  void (*on_close)(Cronet_WebSocketPtr ws, void* user_data,
                   int was_clean, uint16_t code, const char* reason);

  // Called when the connection fails.
  // |net_error| is a Chromium net error code.
  void (*on_error)(Cronet_WebSocketPtr ws, void* user_data,
                   int net_error, const char* message);
} Cronet_WebSocket_Callbacks;

// Create a WebSocket handle bound to the given engine.
// |callbacks| is copied internally. |user_data| is forwarded to every callback.
CRONET_EXPORT Cronet_WebSocketPtr
Cronet_WebSocket_Create(Cronet_EnginePtr engine,
                        const Cronet_WebSocket_Callbacks* callbacks,
                        void* user_data);

// Connect to |url| (ws:// or wss://).
// |sub_protocols| is comma-separated list (may be NULL).
// |origin| is the Origin header (may be NULL).
// |extra_headers| is "\r\n"-delimited "Name: Value" pairs (may be NULL).
//   These headers are added to the HTTP upgrade request in order.
//   Example: "User-Agent: MyApp\r\nAccept-Language: zh-CN\r\n"
// Returns 0 on success, negative on error.
CRONET_EXPORT int
Cronet_WebSocket_Connect(Cronet_WebSocketPtr ws,
                         const char* url,
                         const char* sub_protocols,
                         const char* origin,
                         const char* extra_headers);

// Send a message. Returns 0 on success, negative on error.
CRONET_EXPORT int
Cronet_WebSocket_Send(Cronet_WebSocketPtr ws,
                      Cronet_WebSocket_MessageType type,
                      const void* data, uint64_t len);

// Initiate graceful close. |code| should be 1000-4999.
// |reason| is UTF-8 (may be NULL, max 123 bytes).
CRONET_EXPORT int
Cronet_WebSocket_Close(Cronet_WebSocketPtr ws,
                       uint16_t code, const char* reason);

// Destroy the handle and free all resources.
// Abruptly terminates if still connected.
CRONET_EXPORT void
Cronet_WebSocket_Destroy(Cronet_WebSocketPtr ws);

#ifdef __cplusplus
}
#endif

#endif  // COMPONENTS_CRONET_NATIVE_INCLUDE_CRONET_WEBSOCKET_C_H_
