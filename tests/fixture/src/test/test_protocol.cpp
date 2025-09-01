#include "protocol/handler.h"
#include "protocol/connection.h"
#include <iostream>

extern void report(const char* name, bool passed);

void test_protocol_suite() {
    std::cout << "Protocol tests:" << std::endl;

    {
        Handler handler;
        handler.register_command("echo", [](const std::string& p) { return p; });
        report("handler_register", handler.has_command("echo"));
    }

    {
        Handler handler;
        handler.register_command("greet", [](const std::string& p) {
            return "hello " + p;
        });
        auto result = handler.handle("greet", "world");
        report("handler_dispatch", result == "hello world");
    }

    {
        Connection conn("localhost", 8080);
        report("connection_init", !conn.is_connected());
        conn.connect();
        report("connection_connect", conn.is_connected());
        conn.disconnect();
        report("connection_disconnect", !conn.is_connected());
    }
}
