"""
NAD has an RS232 interface to control the receiver.

Not all receivers have all functions.
Functions can be found on the NAD website: http://nadelectronics.com/software
"""

import codecs
import socket
from time import sleep
import nad_receiver.nad_commands as nad_commands
import threading
import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1
DEFAULT_WRITE_TIMEOUT = 1


class NADReceiver(object):
    """NAD receiver."""

    def __init__(self, serial_port, timeout=DEFAULT_TIMEOUT,
                 write_timeout=DEFAULT_WRITE_TIMEOUT):
        """Create RS232 connection."""
        import serial  # pylint: disable=import-error

        self.ser = serial.Serial(serial_port, baudrate=115200, timeout=timeout,
                                 write_timeout=write_timeout)
        self.lock = threading.Lock()

    def exec_command(self, domain, function, operator, value=None):
        """
        Write a command to the receiver and read the value it returns.

        The receiver will always return a value, also when setting a value.
        """
        if operator in nad_commands.CMDS[domain][function]['supported_operators']:
            if operator is '=' and value is None:
                raise ValueError('No value provided')

            if value is None:
                cmd = ''.join([nad_commands.CMDS[domain]
                               [function]['cmd'], operator])
            else:
                cmd = ''.join(
                    [nad_commands.CMDS[domain][function]['cmd'], operator, str(value)])
        else:
            raise ValueError('Invalid operator provided %s' % operator)

        if not self.ser.is_open:
            self.ser.open()

        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.lock.acquire()

        self.ser.write(''.join(['\r', cmd, '\r']).encode('utf-8'))

        self.ser.read(1)  # NAD uses the prefix and suffix \r.
        # With this we read the first \r and skip it
        msg = self.ser.read_until(bytes('\r'.encode()))
        self.lock.release()

        return msg.decode().strip().split('=')[1]
        # b'Main.Volume=-12\r will return -12

    def main_dimmer(self, operator, value=None):
        """Execute Main.Dimmer."""
        return self.exec_command('main', 'dimmer', operator, value)

    def main_mute(self, operator, value=None):
        """Execute Main.Mute."""
        return self.exec_command('main', 'mute', operator, value)

    def main_power(self, operator, value=None):
        """Execute Main.Power."""
        return self.exec_command('main', 'power', operator, value)

    def main_volume(self, operator, value=None):
        """
        Execute Main.Volume.

        Returns int
        """
        return int(self.exec_command('main', 'volume', operator, value))

    def main_ir(self, operator, value=None):
        """Execute Main.IR."""
        return self.exec_command('main', 'ir', operator, value)

    def main_listeningmode(self, operator, value=None):
        """Execute Main.ListeningMode."""
        return self.exec_command('main', 'listeningmode', operator, value)

    def main_sleep(self, operator, value=None):
        """Execute Main.Sleep."""
        return self.exec_command('main', 'sleep', operator, value)

    def main_source(self, operator, value=None):
        """
        Execute Main.Source.

        Returns int
        """
        return int(self.exec_command('main', 'source', operator, value))

    def main_version(self, operator, value=None):
        """Execute Main.Version."""
        return self.exec_command('main', 'version', operator, value)

    def tuner_am_frequency(self, operator, value=None):
        """Execute Tuner.AM.Frequence."""
        return self.exec_command('tuner', 'am_frequency', operator, value)

    def tuner_am_preset(self, operator, value=None):
        """Execute Tuner.AM.Preset."""
        return self.exec_command('tuner', 'am_preset', operator, value)

    def tuner_band(self, operator, value=None):
        """Execute Tuner.Band."""
        return self.exec_command('tuner', 'band', operator, value)

    def tuner_fm_frequency(self, operator, value=None):
        """Execute Tuner.FM.Frequence."""
        return self.exec_command('tuner', 'fm_frequency', operator, value)

    def tuner_fm_mute(self, operator, value=None):
        """Execute Tuner.FM.Mute."""
        return self.exec_command('tuner', 'fm_mute', operator, value)

    def tuner_fm_preset(self, operator, value=None):
        """Execute Tuner.FM.Preset."""
        return self.exec_command('tuner', 'fm_preset', operator, value)


class NADReceiverTCP(object):
    """
    Support NAD amplifiers that use tcp for communication.

    Known supported model: Nad D 7050.
    """

    POLL_VOLUME = "0001020204"
    POLL_POWER = "0001020209"
    POLL_MUTED = "000102020a"
    POLL_SOURCE = "0001020203"

    CMD_POWERSAVE = "00010207000001020207"
    CMD_OFF = "0001020900"
    CMD_ON = "0001020901"
    CMD_VOLUME = "00010204"
    CMD_MUTE = "0001020a01"
    CMD_UNMUTE = "0001020a00"
    CMD_SOURCE = "00010203"

    SOURCES = {'Coaxial 1': '00', 'Coaxial 2': '01', 'Optical 1': '02',
               'Optical 2': '03', 'Computer': '04', 'Airplay': '05',
               'Dock': '06', 'Bluetooth': '07'}
    SOURCES_REVERSED = {value: key for key, value in
                        SOURCES.items()}

    PORT = 50001

    def __init__(self, host, loop):
        """Setup globals."""
        self._host = host
        self._loop = loop

    async def _send(self, message, read_reply=False):
        """Send a command string to the amplifier."""
        reader, writer = await asyncio.open_connection(self._host, self.PORT,
                                                       loop=self._loop)
        try:
            writer.write(codecs.decode(message, 'hex_codec'))
            if read_reply:
                reply = ''
                while len(reply) < len(message):
                    reply = await asyncio.wait_for(reader.readline(), timeout=10.0)
                return reply.decode('utf-8')
        finally:
            writer.close()

    async def status(self):
        """
        Return the status of the device.

        Returns a dictionary with keys 'Main.Volume' (int 0-200) , 'Main.Power' (bool),
         'Main.Mute' (bool) and 'Main.Source' (str).
        """
        nad_reply = await self._send(self.POLL_VOLUME +
                                     self.POLL_POWER +
                                     self.POLL_MUTED +
                                     self.POLL_SOURCE, read_reply=True)
        if nad_reply is None:
            return

        # split reply into parts of 10 characters
        num_chars = 10
        nad_status = [nad_reply[i:i + num_chars]
                      for i in range(0, len(nad_reply), num_chars)]

        return {'Main.Volume': int(nad_status[0][-2:], 16),
                'Main.Power': nad_status[1][-2:] == '01',
                'Main.Mute': nad_status[2][-2:] == '01',
                'Main.Source': self.SOURCES_REVERSED[nad_status[3][-2:]]}

    async def power_off(self):
        """Power the device off."""
        status = self.status()
        if status['power']:  # Setting power off when it is already off can cause hangs
            await self._send(self.CMD_POWERSAVE + self.CMD_OFF)

    async def power_on(self):
        """Power the device on."""
        status = self.status()
        if not status['power']:
            await self._send(self.CMD_ON, read_reply=True)

    async def set_volume(self, volume):
        """Set volume level of the device. Accepts integer values 0-200."""
        if 0 <= volume <= 200:
            volume = format(volume, "02x")  # Convert to hex
            await self._send(self.CMD_VOLUME + volume)

    async def mute(self):
        """Mute the device."""
        await self._send(self.CMD_MUTE, read_reply=True)

    async def unmute(self):
        """Unmute the device."""
        await self._send(self.CMD_UNMUTE)

    async def select_source(self, source):
        """Select a source from the list of sources."""
        status = self.status()
        if status['power']:  # Changing source when off may hang NAD7050
            # Setting the source to the current source will hang the NAD7050
            if status['source'] != source:
                if source in self.SOURCES:
                    await self._send(self.CMD_SOURCE + self.SOURCES[source], read_reply=True)

    def available_sources(self):
        """Return a list of available sources."""
        return list(self.SOURCES.keys())


class NADReceiverTCPC338(object):
    """
    Support NAD amplifiers that use tcp for communication.

    Known supported model: Nad D C338.
    """

    PORT = 30001

    def __init__(self, host, loop,
                 reconnect_timeout=10,
                 state_changed_timeout=0.1,
                 state_changed_cb=None):
        self._host = host
        self._loop = loop

        self._reconnect_timeout = reconnect_timeout
        self._state_changed_timeout = state_changed_timeout
        self._state_changed_cb = state_changed_cb

        self._reader = None
        self._writer = None

        self._connection_task = None
        self._state_changed_waiter = None
        self._state_changed_task = None

        self._state = {}

    async def _state_changed(self):
        await asyncio.sleep(self._state_changed_timeout)

        if self._state_changed_cb:
            self._state_changed_cb(self._state)

        if self._state_changed_waiter:
            self._state_changed_waiter.set_result(True)

    def _parse_data(self, data):
        _LOGGER.debug("Received data %s", data)

        key, value = data.split('=')
        cmd_desc = nad_commands.C338_CMDS[key]

        # convert the data to the correct type
        if 'type' in cmd_desc:
            if cmd_desc['type'] == bool:
                value = bool(cmd_desc['values'].index(value))
            else:
                value = cmd_desc['type'](value)

        self._state[key] = value

        # volume changes implicitly disables mute
        if key == 'Main.Volume':
            self._state['Main.Mute'] = False

        if self._state_changed_task is None or self._state_changed_task.done():
            self._state_changed_task = self._loop.create_task(self._state_changed())

    async def _connection_loop(self):
        try:
            self._reader, self._writer = await asyncio.open_connection(self._host, self.PORT, loop=self._loop)

            # get state after connecting
            await self.exec_command('Main', '?')

            # read until EOF
            while self._reader and not self._reader.at_eof():
                data = await self._reader.readline()
                if data:
                    self._parse_data(data.decode('utf-8').strip())
        finally:
            # clean up
            if self._state_changed_waiter:
                self._state_changed_waiter.cancel()

            if self._state_changed_task:
                self._state_changed_task.cancel()

            self._writer = None
            self._reader = None

            if self._state:
                self._state.clear()

                if self._state_changed_cb:
                    self._state_changed_cb(self._state)

    async def disconnect(self):
        """Disconnect from the device."""
        _LOGGER.debug("Disconnecting from %s", self._host)

        if self._writer:
            # send EOF, let the connection exit gracefully
            if self._writer.can_write_eof():
                _LOGGER.debug("Disconnect: writing EOF")
                self._writer.write_eof()
            # socket cannot send EOF, cancel connection
            elif self._connection_task:
                _LOGGER.debug("Disconnect: force")
                self._connection_task.cancel()

            await self._connection_task

    async def run_loop(self):
        """Start the connection loop which handles reconnects."""
        while True:
            _LOGGER.debug("Connecting to %s", self._host)
            self._connection_task = self._loop.create_task(self._connection_loop())
            try:
                await self._connection_task
                # EOF reached, break reconnect loop
                _LOGGER.debug("EOF reached")
                break
            except asyncio.CancelledError:
                # force disconnect, break reconnect loop
                _LOGGER.debug("Force disconnect")
                break
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
                _LOGGER.exception("Disconnected, reconnecting in %ss",
                                  self._reconnect_timeout, exc_info=e)
                await asyncio.sleep(self._reconnect_timeout)

    async def exec_command(self, command, operator, value=None):
        """Execute a command on the device."""
        if self._writer:
            cmd_desc = nad_commands.C338_CMDS[command]
            # validate operator
            if operator in cmd_desc['supported_operators']:
                if operator is '=' and value is None:
                    raise ValueError("No value provided")
                elif operator in ['?', '-', '+'] and value is not None:
                    raise ValueError(
                        "Operator \'%s\' cannot be called with a value" % operator)

                if value is None:
                    cmd = command + operator
                else:
                    # validate value
                    if 'values' in cmd_desc:
                        if 'type' in cmd_desc and cmd_desc['type'] == bool:
                            value = cmd_desc['values'][int(value)]
                        elif value not in cmd_desc['values']:
                            raise ValueError("Given value \'%s\' is not one of %s" % (
                                value, cmd_desc['values']))

                    cmd = command + operator + str(value)
            else:
                raise ValueError("Invalid operator provided %s" % operator)

            self._writer.write(cmd.encode('utf-8'))

    async def status(self):
        """
        Return the status of the device.

        Returns a dictionary with keys 'Main.Volume' (int -80-0) , 'Main.Power' (bool),
         'Main.Mute' (bool) and 'Main.Source' (str).
        """
        if self._state_changed_waiter is None or self._state_changed_waiter.done():
            self._state_changed_waiter = self._loop.create_future()

        await self.exec_command('Main', '?')

        # not guaranteed to get the correct response, so just wait until the next state change
        await self._state_changed_waiter

        return self._state

    async def power_off(self):
        """Power the device off."""
        await self.exec_command(nad_commands.CMD_POWER, '=', False)

    async def power_on(self):
        """Power the device on."""
        await self.exec_command(nad_commands.CMD_POWER, '=', True)

    async def set_volume(self, volume):
        """Set volume level of the device in dBa. Accepts integer values -80-0."""
        await self.exec_command(nad_commands.CMD_VOLUME, '=', float(volume))

    async def volume_down(self):
        """Decrease the volume of the device."""
        await self.exec_command(nad_commands.CMD_VOLUME, '-')

    async def volume_up(self):
        """Increase the volume of the device."""
        await self.exec_command(nad_commands.CMD_VOLUME, '+')

    async def mute(self):
        """Mute the device."""
        await self.exec_command(nad_commands.CMD_MUTE, '=', True)

    async def unmute(self):
        """Unmute the device."""
        await self.exec_command(nad_commands.CMD_MUTE, '=', False)

    async def select_source(self, source):
        """Select a source from the list of sources."""
        await self.exec_command(nad_commands.CMD_SOURCE, '=', source)

    def available_sources(self):
        """Return a list of available sources."""
        return list(nad_commands.C338_CMDS[nad_commands.CMD_SOURCE]['values'])


class NADReceiverTelnet(NADReceiver):
    """
    Support NAD amplifiers that use telnet for communication.
    Supports all commands from the RS232 base class

    Known supported model: Nad T787.
    """

    def _open_connection(self):
        import telnetlib

        if not self.telnet:
            try:
                self.telnet = telnetlib.Telnet(self.host, self.port, 3)
                # Some versions of the firmware report Main.Model=T787.
                # some versions do not, we want to clear that line
                self.telnet.read_until('\n'.encode(), self.timeout)
                # Could raise eg. EOFError, UnicodeError
            except:
                return False

        return True

    def _close_connection(self):
        """
        Close any telnet session
        """
        if self.telnet:
            self.telnet.close()

    def __init__(self, host, port=23, timeout=DEFAULT_TIMEOUT):
        """Create NADTelnet."""
        self.telnet = None
        self.host = host
        self.port = port
        self.timeout = timeout
        # __init__ must never raise

    def __del__(self):
        """
        Close any telnet session
        """
        self._close_connection()

    def exec_command(self, domain, function, operator, value=None):
        """
        Write a command to the receiver and read the value it returns.
        """
        if operator in nad_commands.CMDS[domain][function]['supported_operators']:
            if operator is '=' and value is None:
                raise ValueError('No value provided')

            if value is None:
                cmd = ''.join([nad_commands.CMDS[domain]
                               [function]['cmd'], operator])
            else:
                cmd = ''.join(
                    [nad_commands.CMDS[domain][function]['cmd'], operator, str(value)])
        else:
            raise ValueError('Invalid operator provided %s' % operator)

        if self._open_connection():
            # For telnet the first \r / \n is recommended only
            self.telnet.write((''.join(['\r', cmd, '\n']).encode()))
            # Could raise eg. socket.error, UnicodeError, let the client handle it

            # Test 3 x buffer is completely empty
            # With the default timeout that means a delay at
            # about 3+ seconds
            loop = 3
            while loop:
                msg = self.telnet.read_until('\n'.encode(), self.timeout)
                # Could raise eg. EOFError, UnicodeError, let the client handle it

                if msg == "":
                    # Nothing in buffer
                    loop -= 1
                    continue

                msg = msg.decode().strip('\r\n')
                # Could raise eg. UnicodeError, let the client handle it

                # print("NAD reponded with '%s'" % msg)
                # Wait for the response that equals the requested domain.function
                if msg.strip().split('=')[0].lower() == '.'.join([domain, function]).lower():
                    # b'Main.Volume=-12\r will return -12
                    return msg.strip().split('=')[1]

            raise RuntimeError('Failed to read response')

        raise RuntimeError('Failed to open connection')
