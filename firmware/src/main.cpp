#include <Arduino.h>
#include <button.h>

namespace {

constexpr uint8_t kButtonPin = 41;
constexpr uint32_t kButtonDebounceMs = 20;

ButtonDebouncer button(kButtonDebounceMs);

void send_button_event() {
  const char* message = button_event_message(
      button.update(digitalRead(kButtonPin) == LOW, millis()));
  if (message != nullptr) {
    // println would end the line with "\r\n", but the protocol uses "\n".
    Serial.print(message);
    Serial.print('\n');
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(kButtonPin, INPUT_PULLUP);
}

void loop() {
  send_button_event();
}
