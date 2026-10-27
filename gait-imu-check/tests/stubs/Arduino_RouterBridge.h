#pragma once
#include "Arduino.h"
#include <string>
#include <vector>
struct Notification { std::string name; std::vector<double> args; uint32_t at_us; };
extern std::vector<Notification> notifications;
class BridgeClass {
 public:
  String (*status_fn)() = nullptr;
  void begin() {}
  void provide_safe(const char *, String (*f)()) { status_fn = f; }
  template <typename... A> void notify(const char *name, A... a) {
    Notification n; n.name = name; (n.args.push_back((double)a), ...); n.at_us = sim_us; notifications.push_back(n);
  }
};
extern BridgeClass Bridge;
