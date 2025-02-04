import os
import pty
import select
import time
import threading
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from urllib.parse import urlparse
import sys


class MQTTY:
    def __init__(self, mqtt_uri):
        self.mqtt_uri = urlparse(mqtt_uri)

        if self.mqtt_uri.scheme not in ["mqtt", "ws", "wss"]:
            raise ValueError("Invalid URI scheme. Expected 'mqtt://', 'ws://', or 'wss://'.")

        self.mqtt_host = self.mqtt_uri.hostname
        self.mqtt_port = self.mqtt_uri.port or (443 if self.mqtt_uri.scheme == "wss" else 80)
        self.mqtt_transport = "websockets" if self.mqtt_uri.scheme in ["ws", "wss"] else "tcp"

        base_path = self.mqtt_uri.path.lstrip("/")  # Remove leading slash from path
        self.device_serial_input_topic = f"{base_path}/device_serial_input"
        self.device_serial_output_topic = f"{base_path}/device_serial_output"

        self.mqtt_client = mqtt.Client(transport=self.mqtt_transport, callback_api_version=CallbackAPIVersion.VERSION2)

        self.master_fd, self.slave_fd = pty.openpty()  # Create the pseudoterminal
        self.slave_name = os.ttyname(self.slave_fd)

        self.connected = False
        self.stop_event = threading.Event()

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages and write to PTY."""
        try:
            os.write(self.master_fd, msg.payload)
        except Exception as e:
            sys.stderr.write(f"Error writing to PTY: {e}\n")

    def mqtt_connect(self):
        """Attempt to connect to the MQTT broker with retries."""
        self.mqtt_client.on_message = self.on_message

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code == 0:
                self.connected = True
                client.subscribe(self.device_serial_output_topic)  # Subscribe to output topic
            else:
                sys.stderr.write(f"Failed to connect to MQTT broker, return code {reason_code}\n")

        def on_disconnect(client, userdata, reason_code, properties, packet_from_broker):
            self.connected = False

        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_disconnect = on_disconnect

        try:
            self.mqtt_client.connect_async(self.mqtt_host, self.mqtt_port)
            self.mqtt_client.loop_forever()
        except Exception as e:
            sys.stderr.write(f"MQTT connection failed: {e}\n")

    def pty_to_mqtt(self):
        """Read data from PTY and publish it to MQTT."""
        while not self.stop_event.is_set():
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 1)
                if self.master_fd in ready:
                    data = os.read(self.master_fd, 1024)
                    if self.connected:
                        self.mqtt_client.publish(self.device_serial_input_topic, data)  # Publish to input topic
            except Exception as e:
                sys.stderr.write(f"Error reading from PTY: {e}\n")
                break

    def run(self):
        """Start the bridge between PTY and MQTT."""
        print(self.slave_name, flush=True)

        mqtt_thread = threading.Thread(target=self.mqtt_connect)
        mqtt_thread.daemon = True
        mqtt_thread.start()

        try:
            self.pty_to_mqtt()
        except KeyboardInterrupt:
            sys.stderr.write("Shutting down...\n")
        finally:
            self.stop_event.set()
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            os.close(self.master_fd)
            os.close(self.slave_fd)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: mqtty <mqtt_uri>\n")
    else:
        mqtt_uri = sys.argv[1]

        try:
            bridge = MQTTY(mqtt_uri)
            bridge.run()
        except ValueError as e:
            sys.stderr.write(f"Error: {e}\n")


if __name__ == "__main__":
    main()
