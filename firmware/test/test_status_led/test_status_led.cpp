#include <status_led.h>
#include <unity.h>

static constexpr Rgb kOff = {0, 0, 0};

static void assert_rgb(Rgb expected, Rgb actual) {
  TEST_ASSERT_EQUAL_UINT8(expected.r, actual.r);
  TEST_ASSERT_EQUAL_UINT8(expected.g, actual.g);
  TEST_ASSERT_EQUAL_UINT8(expected.b, actual.b);
}

static bool is_off(Rgb color) { return color == kOff; }

void setUp() {}

void tearDown() {}

void test_parses_known_messages() {
  Status status = Status::kBooting;
  TEST_ASSERT_TRUE(parse_status("idle", &status));
  TEST_ASSERT_EQUAL(Status::kIdle, status);
  TEST_ASSERT_TRUE(parse_status("capturing", &status));
  TEST_ASSERT_EQUAL(Status::kCapturing, status);
  TEST_ASSERT_TRUE(parse_status("error", &status));
  TEST_ASSERT_EQUAL(Status::kError, status);
}

void test_ignores_unknown_messages() {
  const char* lines[] = {"", "IDLE", "idle ", " idle", "idl", "idlex", "booting", "disconnected", "press"};
  for (const char* line : lines) {
    Status status = Status::kIdle;
    TEST_ASSERT_FALSE_MESSAGE(parse_status(line, &status), line);
    TEST_ASSERT_EQUAL_MESSAGE(Status::kIdle, status, line);
  }
}

void test_is_booting_until_first_message() {
  StatusTracker tracker;
  TEST_ASSERT_EQUAL(Status::kBooting, tracker.current(0));
  TEST_ASSERT_EQUAL(Status::kBooting, tracker.current(kHeartbeatTimeoutMs * 10));
}

void test_shows_received_status() {
  StatusTracker tracker;
  tracker.receive(Status::kIdle, 100);
  TEST_ASSERT_EQUAL(Status::kIdle, tracker.current(100));
  tracker.receive(Status::kCapturing, 200);
  TEST_ASSERT_EQUAL(Status::kCapturing, tracker.current(200));
  tracker.receive(Status::kError, 300);
  TEST_ASSERT_EQUAL(Status::kError, tracker.current(300));
}

void test_disconnects_when_timeout_elapses() {
  StatusTracker tracker;
  tracker.receive(Status::kIdle, 1000);
  TEST_ASSERT_EQUAL(Status::kIdle, tracker.current(1000 + kHeartbeatTimeoutMs - 1));
  TEST_ASSERT_EQUAL(Status::kDisconnected, tracker.current(1000 + kHeartbeatTimeoutMs));
}

void test_heartbeat_extends_timeout() {
  StatusTracker tracker;
  tracker.receive(Status::kIdle, 0);
  tracker.receive(Status::kIdle, 1000);
  TEST_ASSERT_EQUAL(Status::kIdle, tracker.current(kHeartbeatTimeoutMs + 999));
  TEST_ASSERT_EQUAL(Status::kDisconnected, tracker.current(kHeartbeatTimeoutMs + 1000));
}

void test_reconnects_when_messages_resume() {
  StatusTracker tracker;
  tracker.receive(Status::kIdle, 0);
  TEST_ASSERT_EQUAL(Status::kDisconnected, tracker.current(kHeartbeatTimeoutMs));
  tracker.receive(Status::kCapturing, kHeartbeatTimeoutMs + 500);
  TEST_ASSERT_EQUAL(Status::kCapturing, tracker.current(kHeartbeatTimeoutMs + 500));
}

void test_timeout_survives_millis_wraparound() {
  StatusTracker tracker;
  const uint32_t received = UINT32_MAX - 500;
  tracker.receive(Status::kIdle, received);
  TEST_ASSERT_EQUAL(Status::kIdle, tracker.current(received + kHeartbeatTimeoutMs - 1));
  TEST_ASSERT_EQUAL(Status::kDisconnected, tracker.current(received + kHeartbeatTimeoutMs));
}

void test_stays_disconnected_when_elapsed_time_wraps() {
  StatusTracker tracker;
  tracker.receive(Status::kIdle, 0);
  TEST_ASSERT_EQUAL(Status::kDisconnected, tracker.current(kHeartbeatTimeoutMs));
  TEST_ASSERT_EQUAL(Status::kDisconnected, tracker.current(0));
}

void test_idle_is_steady_green() {
  for (uint32_t t = 0; t < 2000; t += 50) {
    assert_rgb({0, 32, 0}, led_color(Status::kIdle, t));
  }
}

void test_capturing_is_steady_blue() {
  for (uint32_t t = 0; t < 2000; t += 50) {
    assert_rgb({0, 0, 32}, led_color(Status::kCapturing, t));
  }
}

void test_booting_blinks_white_slowly() {
  assert_rgb({24, 24, 24}, led_color(Status::kBooting, 0));
  assert_rgb({24, 24, 24}, led_color(Status::kBooting, 499));
  TEST_ASSERT_TRUE(is_off(led_color(Status::kBooting, 500)));
  TEST_ASSERT_TRUE(is_off(led_color(Status::kBooting, 999)));
  assert_rgb({24, 24, 24}, led_color(Status::kBooting, 1000));
}

void test_error_blinks_red_fast() {
  assert_rgb({32, 0, 0}, led_color(Status::kError, 0));
  assert_rgb({32, 0, 0}, led_color(Status::kError, 149));
  TEST_ASSERT_TRUE(is_off(led_color(Status::kError, 150)));
  TEST_ASSERT_TRUE(is_off(led_color(Status::kError, 299)));
  assert_rgb({32, 0, 0}, led_color(Status::kError, 300));
}

void test_disconnected_flashes_orange_briefly() {
  assert_rgb({32, 10, 0}, led_color(Status::kDisconnected, 0));
  assert_rgb({32, 10, 0}, led_color(Status::kDisconnected, 99));
  TEST_ASSERT_TRUE(is_off(led_color(Status::kDisconnected, 100)));
  TEST_ASSERT_TRUE(is_off(led_color(Status::kDisconnected, 1999)));
  assert_rgb({32, 10, 0}, led_color(Status::kDisconnected, 2000));
}

void test_statuses_are_distinguishable() {
  const Status statuses[] = {Status::kBooting, Status::kIdle, Status::kCapturing, Status::kError,
                             Status::kDisconnected};
  Rgb lit[5];
  for (int i = 0; i < 5; ++i) {
    lit[i] = led_color(statuses[i], 0);
    TEST_ASSERT_FALSE(is_off(lit[i]));
  }
  for (int i = 0; i < 5; ++i) {
    for (int j = i + 1; j < 5; ++j) {
      TEST_ASSERT_TRUE(lit[i] != lit[j]);
    }
  }
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_parses_known_messages);
  RUN_TEST(test_ignores_unknown_messages);
  RUN_TEST(test_is_booting_until_first_message);
  RUN_TEST(test_shows_received_status);
  RUN_TEST(test_disconnects_when_timeout_elapses);
  RUN_TEST(test_heartbeat_extends_timeout);
  RUN_TEST(test_reconnects_when_messages_resume);
  RUN_TEST(test_timeout_survives_millis_wraparound);
  RUN_TEST(test_stays_disconnected_when_elapsed_time_wraps);
  RUN_TEST(test_idle_is_steady_green);
  RUN_TEST(test_capturing_is_steady_blue);
  RUN_TEST(test_booting_blinks_white_slowly);
  RUN_TEST(test_error_blinks_red_fast);
  RUN_TEST(test_disconnected_flashes_orange_briefly);
  RUN_TEST(test_statuses_are_distinguishable);
  return UNITY_END();
}
