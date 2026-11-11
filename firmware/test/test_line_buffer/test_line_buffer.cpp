#include <line_buffer.h>
#include <unity.h>

template <size_t Capacity>
static int push_all(LineBuffer<Capacity>& buffer, const char* input) {
  int completed = 0;
  for (const char* p = input; *p != '\0'; ++p) {
    if (buffer.push(*p)) {
      ++completed;
    }
  }
  return completed;
}

void setUp() {}

void tearDown() {}

void test_completes_line_on_newline() {
  LineBuffer<16> buffer;
  TEST_ASSERT_EQUAL(0, push_all(buffer, "ready"));
  TEST_ASSERT_TRUE(buffer.push('\n'));
  TEST_ASSERT_EQUAL_STRING("ready", buffer.line());
  TEST_ASSERT_EQUAL(5, buffer.length());
}

void test_strips_carriage_return() {
  LineBuffer<16> buffer;
  TEST_ASSERT_EQUAL(1, push_all(buffer, "ready\r\n"));
  TEST_ASSERT_EQUAL_STRING("ready", buffer.line());
}

void test_empty_line() {
  LineBuffer<16> buffer;
  TEST_ASSERT_TRUE(buffer.push('\n'));
  TEST_ASSERT_EQUAL_STRING("", buffer.line());
  TEST_ASSERT_EQUAL(0, buffer.length());
}

void test_starts_new_line_after_completion() {
  LineBuffer<16> buffer;
  TEST_ASSERT_EQUAL(1, push_all(buffer, "ready\n"));
  TEST_ASSERT_EQUAL(1, push_all(buffer, "busy\n"));
  TEST_ASSERT_EQUAL_STRING("busy", buffer.line());
}

void test_accepts_line_of_exact_capacity() {
  LineBuffer<4> buffer;
  TEST_ASSERT_EQUAL(1, push_all(buffer, "abcd\n"));
  TEST_ASSERT_EQUAL_STRING("abcd", buffer.line());
}

void test_discards_line_over_capacity() {
  LineBuffer<4> buffer;
  TEST_ASSERT_EQUAL(0, push_all(buffer, "abcde\n"));
}

void test_recovers_after_discarded_line() {
  LineBuffer<4> buffer;
  TEST_ASSERT_EQUAL(1, push_all(buffer, "abcdefgh\nok\n"));
  TEST_ASSERT_EQUAL_STRING("ok", buffer.line());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_completes_line_on_newline);
  RUN_TEST(test_strips_carriage_return);
  RUN_TEST(test_empty_line);
  RUN_TEST(test_starts_new_line_after_completion);
  RUN_TEST(test_accepts_line_of_exact_capacity);
  RUN_TEST(test_discards_line_over_capacity);
  RUN_TEST(test_recovers_after_discarded_line);
  return UNITY_END();
}
