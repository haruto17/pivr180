#include <button.h>
#include <unity.h>

static const uint32_t kDebounceMs = 20;

void setUp() {}

void tearDown() {}

void test_no_event_while_released() {
  ButtonDebouncer button(kDebounceMs);
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 0));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 1000));
}

void test_press_after_stable_for_debounce_time() {
  ButtonDebouncer button(kDebounceMs);
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 100));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 119));
  TEST_ASSERT_TRUE(ButtonEvent::Pressed == button.update(true, 120));
}

void test_press_is_reported_once() {
  ButtonDebouncer button(kDebounceMs);
  button.update(true, 100);
  TEST_ASSERT_TRUE(ButtonEvent::Pressed == button.update(true, 120));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 121));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 5000));
}

void test_release_after_press() {
  ButtonDebouncer button(kDebounceMs);
  button.update(true, 100);
  button.update(true, 120);
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 200));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 219));
  TEST_ASSERT_TRUE(ButtonEvent::Released == button.update(false, 220));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 300));
}

void test_ignores_bounce_shorter_than_debounce_time() {
  ButtonDebouncer button(kDebounceMs);
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 100));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 105));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 110));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 129));
  TEST_ASSERT_TRUE(ButtonEvent::Pressed == button.update(true, 130));
}

void test_ignores_glitch_while_pressed() {
  ButtonDebouncer button(kDebounceMs);
  button.update(true, 100);
  button.update(true, 120);
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(false, 200));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 210));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 1000));
}

void test_handles_millis_overflow() {
  ButtonDebouncer button(kDebounceMs);
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 0xFFFFFFF0u));
  TEST_ASSERT_TRUE(ButtonEvent::None == button.update(true, 0x00000002u));
  TEST_ASSERT_TRUE(ButtonEvent::Pressed == button.update(true, 0x00000004u));
}

void test_messages() {
  TEST_ASSERT_EQUAL_STRING("press", button_event_message(ButtonEvent::Pressed));
  TEST_ASSERT_EQUAL_STRING("release",
                           button_event_message(ButtonEvent::Released));
  TEST_ASSERT_NULL(button_event_message(ButtonEvent::None));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_no_event_while_released);
  RUN_TEST(test_press_after_stable_for_debounce_time);
  RUN_TEST(test_press_is_reported_once);
  RUN_TEST(test_release_after_press);
  RUN_TEST(test_ignores_bounce_shorter_than_debounce_time);
  RUN_TEST(test_ignores_glitch_while_pressed);
  RUN_TEST(test_handles_millis_overflow);
  RUN_TEST(test_messages);
  return UNITY_END();
}
