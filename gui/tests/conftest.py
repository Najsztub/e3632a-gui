def pytest_addoption(parser):
    parser.addoption("--real", action="store_true", default=False,
                     help="run against real GPIB hardware (addr 1)")
