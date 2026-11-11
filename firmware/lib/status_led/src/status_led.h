#pragma once

#include <stdint.h>

enum class Status { kBooting, kIdle, kCapturing, kError, kDisconnected };

constexpr uint32_t kHeartbeatTimeoutMs = 3000;

bool parse_status(const char* line, Status* status);

class StatusTracker {
 public:
  void receive(Status status, uint32_t now_ms);

  Status current(uint32_t now_ms);

 private:
  Status status_ = Status::kBooting;
  uint32_t last_received_ms_ = 0;
};

struct Rgb {
  uint8_t r;
  uint8_t g;
  uint8_t b;

  bool operator==(const Rgb& other) const {
    return r == other.r && g == other.g && b == other.b;
  }
  bool operator!=(const Rgb& other) const { return !(*this == other); }
};

Rgb led_color(Status status, uint32_t now_ms);
