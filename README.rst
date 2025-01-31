
MQTTY
========

**MQTTY** bridges MQTT topics to a pseudo-terminal (PTY) device, enabling applications like `picocom` to interact with MQTT topics through a virtual serial device.

Installation
------------

Install dependencies:

.. code-block:: bash

    pip install paho-mqtt

Run the project:

.. code-block:: bash

    python src/mqtty/mqtty.py mqtt://<mqtt_host>:<mqtt_port>/topic/data

License
-------

MIT License
