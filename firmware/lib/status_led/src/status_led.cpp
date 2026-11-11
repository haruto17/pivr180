#include "status_led.h"

#include <string.h>

namespace {

constexpr Rgb kOff = {0, 0, 0};
constexpr Rgb kWhite = {24, 24, 24};
constexpr Rgb kGreen = {0, 32, 0};
constexpr Rgb kBlue = {0, 0, 32};
constexpr Rgb kRed = {32, 0, 0};
constexpr Rgb kOrange = {32, 10, 0};

Rgb blink(Rgb color, uint32_t now_ms, uint32_t on_ms, uint32_t period_ms) {
  return now_ms % period_ms < on_ms ? color : kOff;
}

}  // namespace

bool parse_status(const char* line, Status* status) {
  if (strcmp(line, "idle") == 0) {
    *status = Status::kIdle;
  } else if (strcmp(line, "capturing") == 0) {
    *status = Status::kCapturing;
  } else if (strcmp(line, "error") == 0) {
    *status = Status::kError;
  } else {
    return false;
  }
  return true;
}

void StatusTracker::receive(Status status, uint32_t now_ms) {
  status_ = status;
  last_received_ms_ = now_ms;
}

Status StatusTracker::current(uint32_t now_ms) {
  if (status_ == Status::kBooting || status_ == Status::kDisconnected) {
    return status_;
  }
  if (now_ms - last_received_ms_ >= kHeartbeatTimeoutMs) {
    // Latched so that the elapsed time cannot wrap around and revive a stale state.
    status_ = Status::kDisconnected;
  }
  return status_;
}

Rgb led_color(Status status, uint32_t now_ms) {
  switch (status) {
    case Status::kBooting:
      return blink(kWhite, now_ms, 500, 1000);
    case Status::kIdle:
      return kGreen;
    case Status::kCapturing:
      return kBlue;
    case Status::kError:
      return blink(kRed, now_ms, 150, 300);
    case Status::kDisconnected:
      return blink(kOrange, now_ms, 100, 2000);
  }
  return kOff;
}
