#pragma once

#include <stddef.h>

template <size_t Capacity>
class LineBuffer {
  static_assert(Capacity > 0, "Capacity must be positive");

 public:
  bool push(char c) {
    if (complete_) {
      length_ = 0;
      complete_ = false;
    }
    if (c == '\r') {
      return false;
    }
    if (c == '\n') {
      if (overflowed_) {
        overflowed_ = false;
        length_ = 0;
        return false;
      }
      buffer_[length_] = '\0';
      complete_ = true;
      return true;
    }
    if (overflowed_) {
      return false;
    }
    if (length_ == Capacity) {
      // Truncating instead would let a cut-off message be read as a valid one.
      overflowed_ = true;
      return false;
    }
    buffer_[length_++] = c;
    return false;
  }

  const char* line() const { return buffer_; }

  size_t length() const { return length_; }

 private:
  char buffer_[Capacity + 1] = {};
  size_t length_ = 0;
  bool complete_ = false;
  bool overflowed_ = false;
};
