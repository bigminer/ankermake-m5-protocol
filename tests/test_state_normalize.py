import unittest

from web.service.state import normalize


class NormalizeTests(unittest.TestCase):

    def test_print_job_status(self):
        self.assertEqual(
            normalize({
                "commandType": 1001,
                "name": "cube.gcode",
                "progress": 4200,
                "totalTime": 65,
                "time": 125,
                "img": "http://printer.local/preview.jpg",
                "state": "printing",
            }),
            {
                "state": "printing",
                "print": {
                    "name": "cube.gcode",
                    "elapsed": 65,
                    "remaining": 125,
                    "progress": 4200,
                    "img": "http://printer.local/preview.jpg",
                },
            },
        )

    def test_print_job_partial(self):
        self.assertEqual(normalize({"commandType": 1001, "name": "job.gcode"}),
                         {"print": {"name": "job.gcode"}})

    def test_nozzle_temp(self):
        self.assertEqual(normalize({"commandType": 1003, "currentTemp": 21500, "targetTemp": 4000}),
                         {"nozzle": {"current": 21500, "target": 4000}})

    def test_nozzle_temp_without_target(self):
        self.assertEqual(normalize({"commandType": 1003, "currentTemp": 2100}),
                         {"nozzle": {"current": 2100}})

    def test_bed_temp(self):
        self.assertEqual(normalize({"commandType": 1004, "currentTemp": 3300, "targetTemp": 3500}),
                         {"bed": {"current": 3300, "target": 3500}})

    def test_speed(self):
        self.assertEqual(normalize({"commandType": 1006, "value": 100}), {"speed": 100})

    def test_layer(self):
        self.assertEqual(normalize({"commandType": 1052, "real_print_layer": 3, "total_layer": 20}),
                         {"print": {"layer": {"current": 3, "total": 20}}})

    def test_state_rides_on_any_notice(self):
        # a notice the UI otherwise ignores still surfaces its state string
        self.assertEqual(normalize({"commandType": 999, "state": "idle"}), {"state": "idle"})

    def test_state_alternate_key(self):
        self.assertEqual(normalize({"commandType": 999, "machineStatus": 7}), {"state": "7"})

    def test_unhandled_notice_is_dropped(self):
        self.assertEqual(normalize({"commandType": 999, "foo": "bar"}), {})

    def test_no_command_type(self):
        self.assertEqual(normalize({"foo": "bar"}), {})


if __name__ == "__main__":
    unittest.main()
