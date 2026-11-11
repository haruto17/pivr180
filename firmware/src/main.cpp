#include <Arduino.h>
#include <line_buffer.h>
#include <status_led.h>

namespace {

constexpr uint8_t kLedPin = 35;

LineBuffer<32> rx_buffer;
StatusTracker status_tracker;
Rgb shown_color = {0, 0, 0};

void update_status_led() {
  while (Serial.available() > 0) {
    Status status;
    if (rx_buffer.push(static_cast<char>(Serial.read())) &&
        parse_status(rx_buffer.line(), &status)) {
      status_tracker.receive(status, millis());
    }
  }
  const uint32_t now = millis();
  const Rgb color = led_color(status_tracker.current(now), now);
  // Rewriting an unchanged colour would block on the RMT transfer every loop.
  if (color != shown_color) {
    neopixelWrite(kLedPin, color.r, color.g, color.b);
    shown_color = color;
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  neopixelWrite(kLedPin, shown_color.r, shown_color.g, shown_color.b);
}

void loop() {
  update_status_led();
}
