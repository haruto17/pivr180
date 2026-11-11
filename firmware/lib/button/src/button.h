#pragma once

#include <stdint.h>

enum class ButtonEvent { None, Pressed, Released };

class ButtonDebouncer {
 public:
  explicit ButtonDebouncer(uint32_t debounce_ms) : debounce_ms_(debounce_ms) {}

  ButtonEvent update(bool pressed, uint32_t now_ms) {
    if (pressed != raw_) {
      raw_ = pressed;
      raw_changed_at_ms_ = now_ms;
      return ButtonEvent::None;
    }
    if (raw_ == stable_ || now_ms - raw_changed_at_ms_ < debounce_ms_) {
      return ButtonEvent::None;
    }
    stable_ = raw_;
    return stable_ ? ButtonEvent::Pressed : ButtonEvent::Released;
  }

 private:
  uint32_t debounce_ms_;
  bool raw_ = false;
  bool stable_ = false;
  uint32_t raw_changed_at_ms_ = 0;
};

inline const char* button_event_message(ButtonEvent event) {
  switch (event) {
    case ButtonEvent::Pressed:
      return "press";
    case ButtonEvent::Released:
      return "release";
    case ButtonEvent::None:
      break;
  }
  return nullptr;
}
