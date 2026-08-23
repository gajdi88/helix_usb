import logging
import signal
import sys

from helix_usb import HelixUsb
from modules import modules as module_catalog
from utils.usb_monitor import UsbMonitor


QT_BINDING = None
try:
	from PySide6.QtCore import QObject, Qt, QTimer, Signal
	from PySide6.QtGui import QPainter, QPen
	from PySide6.QtWidgets import (
		QAbstractItemView,
		QApplication,
		QCheckBox,
		QFrame,
		QGridLayout,
		QHBoxLayout,
		QLabel,
		QListWidget,
		QListWidgetItem,
		QMainWindow,
		QMessageBox,
		QPlainTextEdit,
		QPushButton,
		QSlider,
		QSplitter,
		QStyle,
		QVBoxLayout,
		QWidget,
	)
	QT_BINDING = "PySide6"
except ImportError:
	from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal as Signal
	from PyQt6.QtGui import QPainter, QPen
	from PyQt6.QtWidgets import (
		QAbstractItemView,
		QApplication,
		QCheckBox,
		QFrame,
		QGridLayout,
		QHBoxLayout,
		QLabel,
		QListWidget,
		QListWidgetItem,
		QMainWindow,
		QMessageBox,
		QPlainTextEdit,
		QPushButton,
		QSlider,
		QSplitter,
		QStyle,
		QVBoxLayout,
		QWidget,
	)
	QT_BINDING = "PyQt6"


log = logging.getLogger(__name__)


def normalize_preset_names(preset_names):
	"""Pad or trim an incoming name list to the device's preset count.

	Reads the count from HelixUsb rather than keeping a copy. The UI used to
	hold its own PRESET_LIST_COUNT, which stayed at the HX Stomp's 125 when
	the rest of the fork moved to the Helix LT's 128 -- the device sent 128
	names, HelixUsb stored 128, and the list silently dropped the last three.
	"""
	count = HelixUsb.PRESET_LIST_COUNT
	names = list(preset_names[:count])
	if len(names) < count:
		names.extend([HelixUsb.PRESET_PLACEHOLDER_NAME] * (count - len(names)))
	elif len(preset_names) > count:
		log.warning('Preset-name list longer than %d; showing the first %d', count, count)
	return names


# The Helix LT has two DSP paths, each with an upper and lower row of eight
# block positions. The HX Stomp's single row of eight does not apply.
BLOCK_ROW_NAMES = ('Path 1 upper', 'Path 1 lower', 'Path 2 upper', 'Path 2 lower')
BLOCKS_PER_ROW = 8


COLOR_HEX = {
	"off": "#3a3a3a",
	"white": "#d9d9d9",
	"red": "#be4d4d",
	"dark_orange": "#bf6b2d",
	"light_orange": "#d6923c",
	"yellow": "#b9a03c",
	"green": "#4da05f",
	"turquoise": "#3f9c9a",
	"blue": "#4f74bb",
	"violet": "#8564bf",
	"pink": "#b96695",
	"auto_color": "#6d6d6d",
}

ICON_BY_CATEGORY = {
	"Distortion": "🟧",
	"Dynamic": "📈",
	"EQ": "🎚",
	"Modulation": "🌀",
	"Delay": "⏱",
	"Reverb": "🌊",
	"Pitch/Synth": "🎹",
	"Amp": "🔊",
	"Cab": "🧱",
	"Amp+Cab": "🎛",
	"Wah": "🦶",
	"Volume/Pan": "🎚",
	"Send/Return": "🔁",
	"MIDI": "🎼",
	"Looper": "🔄",
}


class QtLogHandler(logging.Handler, QObject):
	message = Signal(str)

	def __init__(self):
		logging.Handler.__init__(self)
		QObject.__init__(self)

	def emit(self, record):
		try:
			self.message.emit(self.format(record))
		except Exception:
			pass


class SignalChainPanel(QFrame):
	def __init__(self, parent=None):
		super().__init__(parent)
		self._line_color = "#d6923c"
		self._left_endpoint = None
		self._right_endpoint = None

	def set_endpoints(self, left_widget, right_widget):
		self._left_endpoint = left_widget
		self._right_endpoint = right_widget
		self.update()

	def paintEvent(self, event):
		super().paintEvent(event)
		painter = QPainter(self)
		pen = QPen()
		pen.setColor(Qt.GlobalColor.transparent)
		painter.setPen(pen)

		try:
			line_pen = QPen()
			line_pen.setWidth(2)
			line_pen.setColor(self.palette().color(self.foregroundRole()))
			line_pen.setColor(self._qt_color(self._line_color))
			painter.setPen(line_pen)
			y = int(self.height() * 0.30)
			block_buttons = self.findChildren(QPushButton, "slotButton")
			if len(block_buttons) > 0:
				btn_center = block_buttons[0].mapTo(self, block_buttons[0].rect().center())
				y = btn_center.y()
			x_start = 8
			x_end = max(8, self.width() - 8)
			if self._left_endpoint is not None:
				left_center = self._left_endpoint.mapTo(self, self._left_endpoint.rect().center())
				x_start = left_center.x()
				y = left_center.y()
			if self._right_endpoint is not None:
				right_center = self._right_endpoint.mapTo(self, self._right_endpoint.rect().center())
				x_end = right_center.x()
			painter.drawLine(x_start, y, x_end, y)
		except Exception:
			pass

	def _qt_color(self, hex_color):
		try:
			from PySide6.QtGui import QColor
		except Exception:
			from PyQt6.QtGui import QColor
		return QColor(hex_color)


class HelixBridge(QObject):
	preset_names_changed = Signal(list)
	preset_no_changed = Signal(int)
	slot_data_changed = Signal(int, object)
	snapshot_changed = Signal(int)
	preset_layout_changed = Signal(object)
	snapshot_names_changed = Signal(list)
	setlist_names_changed = Signal(list)
	connection_changed = Signal(bool)
	status = Signal(str)

	def __init__(self):
		super().__init__()
		self.helix = HelixUsb()
		self.usb_monitor = None
		self._last_connected = None
		self._requested_initial_names = False
		self._stopped = False

		self.helix.register_preset_names_change_cb_fct(self._on_preset_names)
		self.helix.register_preset_no_change_cb_fct(self._on_preset_no)
		self.helix.register_slot_data_change_cb_fct(self._on_slot_data)
		self.helix.register_snapshot_change_cb_fct(self._on_snapshot)
		self.helix.register_preset_layout_change_cb_fct(self._on_preset_layout)
		self.helix.register_setlist_names_change_cb_fct(self._on_setlist_names)
		self.helix.register_snapshot_names_change_cb_fct(self._on_snapshot_names)

		self.connection_poll = QTimer(self)
		self.connection_poll.setInterval(400)
		self.connection_poll.timeout.connect(self._poll_connection)

	def start(self):
		self.status.emit(f"Starting UI bridge ({QT_BINDING})")
		self.usb_monitor = UsbMonitor(['0e41:4246', '0e41:424a', '0e41:5055'])
		self.usb_monitor.register_device_found_cb(self.helix.usb_device_found_cb)
		self.usb_monitor.register_device_lost_cb(self.helix.usb_device_lost_cb)
		self.usb_monitor.start()
		self.helix.usb_monitor = self.usb_monitor
		self.connection_poll.start()
		self.status.emit("USB monitor started; waiting for HX device")

	def stop(self):
		# Reachable twice: once from closeEvent, once from main()'s finally
		# after a SIGTERM-driven quit.
		if self._stopped:
			return
		self._stopped = True
		self.connection_poll.stop()
		if self.helix is not None:
			self.helix.shutdown(self.usb_monitor)
		self.status.emit("Shutdown complete")

	def request_preset_names(self):
		self.status.emit("Requesting preset names")
		self.helix.switch_mode("RequestPresetNames")

	def request_current_preset_data(self):
		self.status.emit("Requesting current preset block layout")
		self.helix.switch_mode("RequestPreset")

	def select_preset(self, preset_no):
		ok = self.helix.send_midi_program_change(preset_no)
		if ok:
			self.status.emit(f"Sent command: p {preset_no}")
		else:
			self.status.emit(f"Failed command: p {preset_no}")

	def step_up(self):
		self.helix.step_preset_up()
		self.status.emit("Sent command: pu")

	def step_down(self):
		self.helix.step_preset_down()
		self.status.emit("Sent command: pd")

	def _on_preset_names(self, preset_names):
		self.preset_names_changed.emit(list(preset_names))

	def _on_setlist_names(self, names):
		self.setlist_names_changed.emit(list(names))

	def _on_preset_layout(self, layout):
		self.preset_layout_changed.emit(layout)

	def _on_snapshot(self, snapshot_no):
		self.snapshot_changed.emit(int(snapshot_no))

	def _on_snapshot_names(self, names):
		self.snapshot_names_changed.emit(list(names))

	def _on_preset_no(self, preset_no):
		self.preset_no_changed.emit(preset_no)

	def _on_slot_data(self, slot_no, slot_info):
		self.slot_data_changed.emit(slot_no, slot_info)

	def _poll_connection(self):
		connected = bool(self.helix.connected)
		if connected != self._last_connected:
			self._last_connected = connected
			self.connection_changed.emit(connected)
			if connected:
				self.status.emit("HX device connected")
			else:
				self.status.emit("HX device disconnected")

		if connected and not self._requested_initial_names and not self.helix.got_preset_names:
			self._requested_initial_names = True
			# Setlist names first, so the preset list can be labelled with the
			# name the front panel shows rather than a bare number. Only one
			# mode runs at a time, so the preset-name request follows once
			# that has had time to complete.
			self.helix.switch_mode("RequestSetlistNames")
			QTimer.singleShot(3000, self.request_preset_names)


class MainWindow(QMainWindow):
	def __init__(self):
		super().__init__()
		self.setWindowTitle("HX Linux")
		self.resize(1200, 760)

		self.bridge = HelixBridge()
		self._slot_index_map = {}
		self._slot_button_widgets = {}
		self._slot_type_label_widgets = {}
		self._slot_info_cache = {}
		self._layout_rows = []
		self._selected_slot_no = 1

		self._build_ui()
		self._connect_signals()
		self.bridge.start()

	def closeEvent(self, event):
		self.bridge.stop()
		super().closeEvent(event)

	def _build_ui(self):
		root = QWidget(self)
		self.setCentralWidget(root)
		main_layout = QVBoxLayout(root)

		splitter = QSplitter(Qt.Orientation.Horizontal)
		splitter.setChildrenCollapsible(False)
		splitter.setHandleWidth(0)
		main_layout.addWidget(splitter, 1)

		left_panel = QWidget()
		left_layout = QVBoxLayout(left_panel)
		splitter.addWidget(left_panel)

		preset_header = QLabel("Presets")
		preset_header.setObjectName("sectionHeader")
		self.preset_header = preset_header
		left_layout.addWidget(preset_header)

		self.preset_list = QListWidget()
		self.preset_list.setAlternatingRowColors(True)
		left_layout.addWidget(self.preset_list, 1)

		btn_row_1 = QHBoxLayout()
		self.btn_refresh_presets = QPushButton("Refresh")
		self.btn_preset_up = QPushButton("↑")
		self.btn_preset_down = QPushButton("↓")
		btn_row_1.addWidget(self.btn_refresh_presets)
		btn_row_1.addWidget(self.btn_preset_up)
		btn_row_1.addWidget(self.btn_preset_down)
		left_layout.addLayout(btn_row_1)

		preset_metrics = self.preset_list.fontMetrics()
		preset_text_width = preset_metrics.horizontalAdvance("000: " + ("W" * 16))
		scrollbar_width = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
		list_frame_width = self.preset_list.frameWidth() * 2
		list_content_padding = 24
		list_min_width = preset_text_width + scrollbar_width + list_frame_width + list_content_padding

		btn_spacing = max(0, btn_row_1.spacing())
		button_row_min_width = (
			self.btn_refresh_presets.sizeHint().width()
			+ self.btn_preset_up.sizeHint().width()
			+ self.btn_preset_down.sizeHint().width()
			+ (2 * btn_spacing)
		)

		left_margins = left_layout.contentsMargins()
		left_panel_width = max(list_min_width, button_row_min_width, preset_header.sizeHint().width())
		left_panel_width += left_margins.left() + left_margins.right()
		left_panel.setFixedWidth(left_panel_width)

		right_panel = QWidget()
		right_layout = QVBoxLayout(right_panel)
		splitter.addWidget(right_panel)

		block_header_row = QHBoxLayout()
		block_header = QLabel("Current Preset Blocks")
		block_header.setObjectName("sectionHeader")
		self.btn_refresh_blocks = QPushButton("Refresh Blocks")
		block_header_row.addWidget(block_header)
		block_header_row.addStretch()
		block_header_row.addWidget(self.btn_refresh_blocks)
		right_layout.addLayout(block_header_row)

		block_row_wrap = QWidget()
		block_row_layout = QHBoxLayout(block_row_wrap)
		block_row_layout.setContentsMargins(0, 0, 0, 0)
		block_row_layout.setSpacing(12)
		right_layout.addWidget(block_row_wrap, 0)

		# Four rows of eight: Path 1 upper/lower, Path 2 upper/lower. The HX
		# Stomp's single strip of eight is not the LT's shape.
		self._block_buttons = {}
		self._row_connectors = {}
		self._row_captions = {}
		self._row_routing_labels = {}
		grid_panel = QFrame()
		grid_panel.setObjectName("blockStripPanel")
		grid_layout = QVBoxLayout(grid_panel)
		grid_layout.setContentsMargins(10, 8, 10, 8)
		grid_layout.setSpacing(4)

		for row_index, row_name in enumerate(BLOCK_ROW_NAMES):
			row_widget = QWidget()
			row_layout = QHBoxLayout(row_widget)
			row_layout.setContentsMargins(0, 0, 0, 0)
			row_layout.setSpacing(6)

			caption = QLabel(row_name)
			caption.setObjectName("rowCaption")
			caption.setFixedWidth(92)
			row_layout.addWidget(caption)
			self._row_captions[row_index] = caption

			self._row_connectors[row_index] = []
			for position in range(1, BLOCKS_PER_ROW + 1):
				if position > 1:
					# The wire between two blocks. Lit on an active row so the
					# signal path is visible even where the slots are empty.
					link = QLabel("")
					link.setObjectName("chainLink")
					link.setFixedSize(10, 34)
					row_layout.addWidget(link)
					self._row_connectors[row_index].append(link)
				btn = QPushButton("-")
				btn.setObjectName("slotButton")
				btn.setCheckable(True)
				btn.setFixedSize(96, 30)
				btn.clicked.connect(
					lambda _checked, r=row_index, pos=position: self._on_block_clicked(r, pos))
				row_layout.addWidget(btn)
				self._block_buttons[(row_index, position)] = btn

			routing_label = QLabel("")
			routing_label.setObjectName("slotTypeLabel")
			routing_label.setMinimumWidth(150)
			row_layout.addWidget(routing_label)
			self._row_routing_labels[row_index] = routing_label

			row_layout.addStretch()
			grid_layout.addWidget(row_widget)

		block_row_layout.addWidget(grid_panel, 1)

		snapshot_row = QHBoxLayout()
		snapshot_row.setSpacing(6)
		snapshot_header = QLabel("Snapshots")
		snapshot_header.setObjectName("sectionHeader")
		right_layout.addWidget(snapshot_header)

		# Display only. Selecting a snapshot would write device state, which
		# this tool does not do without being asked.
		self.snapshot_labels = []
		for idx in range(HelixUsb.SNAPSHOT_COUNT):
			pill = QLabel('SNAPSHOT {}'.format(idx + 1))
			pill.setObjectName("snapshotPill")
			pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
			snapshot_row.addWidget(pill, 1)
			self.snapshot_labels.append(pill)
		right_layout.addLayout(snapshot_row)
		self._refresh_snapshot_pills()

		details_row = QHBoxLayout()
		details_row.setSpacing(10)
		right_layout.addLayout(details_row)

		self.device_type_panel = QFrame()
		self.device_type_panel.setObjectName("blockInfoPanel")
		device_type_layout = QVBoxLayout(self.device_type_panel)
		device_type_layout.setContentsMargins(10, 10, 10, 10)
		device_type_layout.setSpacing(6)
		device_type_layout.addWidget(QLabel("Device Type"))
		self.device_type_list = QListWidget()
		self.device_type_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
		device_type_layout.addWidget(self.device_type_list, 1)

		self.module_name_panel = QFrame()
		self.module_name_panel.setObjectName("blockInfoPanel")
		module_name_layout = QVBoxLayout(self.module_name_panel)
		module_name_layout.setContentsMargins(10, 10, 10, 10)
		module_name_layout.setSpacing(6)
		module_name_layout.addWidget(QLabel("Module Name"))
		self.module_name_list = QListWidget()
		self.module_name_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
		module_name_layout.addWidget(self.module_name_list, 1)

		self.module_settings_panel = QFrame()
		self.module_settings_panel.setObjectName("blockInfoPanel")
		settings_layout = QVBoxLayout(self.module_settings_panel)
		settings_layout.setContentsMargins(10, 10, 10, 10)
		settings_layout.setSpacing(6)
		settings_layout.addWidget(QLabel("Module Settings"))
		self.block_info_slot = QLabel("Slot: --")
		settings_layout.addWidget(self.block_info_slot)
		self.module_settings_container = QWidget()
		self.module_settings_layout = QVBoxLayout(self.module_settings_container)
		self.module_settings_layout.setContentsMargins(0, 0, 0, 0)
		self.module_settings_layout.setSpacing(6)
		settings_layout.addWidget(self.module_settings_container, 1)

		details_row.addWidget(self.device_type_panel, 2)
		details_row.addWidget(self.module_name_panel, 2)
		details_row.addWidget(self.module_settings_panel, 6)

		self._populate_device_type_list()

		status_row = QHBoxLayout()
		self.lbl_connection = QLabel("Connection: Unknown")
		self.lbl_connection.setObjectName("statusPill")
		status_row.addWidget(self.lbl_connection)
		status_row.addStretch()
		self.chk_show_debug_console = QCheckBox("Show Debug Console")
		self.chk_show_debug_console.setChecked(False)
		status_row.addWidget(self.chk_show_debug_console)
		main_layout.addLayout(status_row)

		self.log_view = QPlainTextEdit()
		self.log_view.setReadOnly(True)
		self.log_view.setMaximumBlockCount(400)
		self.log_view.setVisible(False)
		main_layout.addWidget(self.log_view)

		splitter.setStretchFactor(0, 0)
		splitter.setStretchFactor(1, 1)
		splitter.setSizes([left_panel.width(), 1])
		self._apply_styles()
		self._refresh_block_strip_visuals()

	def _connect_signals(self):
		self.btn_refresh_presets.clicked.connect(self.bridge.request_preset_names)
		self.btn_preset_up.clicked.connect(self.bridge.step_down)
		self.btn_preset_down.clicked.connect(self.bridge.step_up)
		self.btn_refresh_blocks.clicked.connect(self.bridge.request_current_preset_data)
		self.preset_list.itemDoubleClicked.connect(self._on_preset_double_clicked)
		self.chk_show_debug_console.toggled.connect(self.log_view.setVisible)

		self.bridge.preset_names_changed.connect(self._on_preset_names_changed)
		self.bridge.snapshot_changed.connect(self._on_snapshot_changed)
		self.bridge.preset_layout_changed.connect(self._on_preset_layout_changed)
		self.bridge.snapshot_names_changed.connect(self._on_snapshot_names_changed)
		self.bridge.setlist_names_changed.connect(self._on_setlist_names_changed)
		self.bridge.preset_no_changed.connect(self._on_preset_no_changed)
		self.bridge.slot_data_changed.connect(self._on_slot_data_changed)
		self.bridge.connection_changed.connect(self._on_connection_changed)
		self.bridge.status.connect(self._append_status)

		log_handler = QtLogHandler()
		log_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
		log_handler.message.connect(self._append_log)
		logging.getLogger().addHandler(log_handler)

	def _apply_styles(self):
		self.setStyleSheet(
			"""
			QMainWindow, QWidget {
				background-color: #1d1f22;
				color: #e7e7e7;
				font-size: 13px;
			}
			QPushButton {
				background-color: #2c3138;
				border: 1px solid #3a4049;
				border-radius: 6px;
				padding: 8px 12px;
			}
			QPushButton:hover {
				background-color: #373d45;
			}
			QListWidget {
				background-color: #17191c;
				border: 1px solid #343941;
				border-radius: 8px;
			}
			QListWidget::item:selected {
				background-color: #6a4b2a;
			}
			#sectionHeader {
				font-size: 15px;
				font-weight: 600;
				padding-bottom: 6px;
			}
			#slotFrame {
				border-radius: 8px;
				border: 1px solid #3a3f46;
				padding: 6px;
				background-color: #2d3239;
			}
			#blockStripPanel {
				background-color: transparent;
				border: none;
			}
			#blockInfoPanel {
				background-color: #17191c;
				border: 1px solid #343941;
				border-radius: 10px;
			}
			#slotButton {
				font-size: 24px;
				font-weight: 600;
				padding: 0px;
				border-radius: 6px;
				border: 1px solid #3a3f46;
				background-color: #2d3239;
				text-align: center;
			}
			#slotButton:checked {
				border: 1px solid #d6923c;
			}
			#slotTypeLabel {
				font-size: 10px;
				font-weight: 600;
				padding: 0px;
				background: transparent;
			}
			#ioEndpoint {
				font-size: 24px;
				color: #aeb3ba;
				padding: 0px 2px;
				border: none;
				background-color: transparent;
			}
			#slotTitle {
				color: #c6c6c6;
				font-size: 11px;
				font-weight: 600;
			}
			#statusPill {
				padding: 5px 10px;
				border-radius: 10px;
				background-color: #2b3037;
				border: 1px solid #3d444f;
			}
			QPlainTextEdit {
				background-color: #141619;
				border: 1px solid #343941;
				border-radius: 8px;
				font-family: monospace;
			}
			"""
		)

	def _append_log(self, message):
		self.log_view.appendPlainText(message)

	def _append_status(self, message):
		self.log_view.appendPlainText(f"[status] {message}")

	def _on_connection_changed(self, connected):
		if connected:
			self.lbl_connection.setText("Connection: Connected")
			self.lbl_connection.setStyleSheet("#statusPill { background: #245034; border: 1px solid #2f7f4e; }")
		else:
			self.lbl_connection.setText("Connection: Waiting for device")
			self.lbl_connection.setStyleSheet("#statusPill { background: #4d3030; border: 1px solid #764242; }")

	# Empty slots must not compete with real blocks for attention, and the
	# label has to fit: 12 characters at the old size were unreadable.
	BLOCK_FONT = "font-size: 10px; font-weight: normal;"
	STYLE_EMPTY = ("#slotButton { background: transparent; border: 1px solid #2b2f36;"
				   " border-radius: 4px; color: #4c525a; %s }" % BLOCK_FONT)
	STYLE_EMPTY_ACTIVE = ("#slotButton { background: transparent; border: 1px solid #3d444d;"
						  " border-radius: 4px; color: #6a7079; %s }" % BLOCK_FONT)
	STYLE_BLOCK = ("#slotButton { background: %s; border: 1px solid #3a3f46;"
				   " border-radius: 4px; color: #10131a; " + BLOCK_FONT + " }")
	STYLE_BYPASSED = ("#slotButton { background: #2d3239; border: 1px dashed %s;"
					  " border-radius: 4px; color: #8b9198; font-style: italic; "
					  + BLOCK_FONT + " }")
	LINK_LIVE = "#chainLink { border-top: 2px solid #5c6672; }"
	LINK_DEAD = "#chainLink { border-top: 2px dotted #262a30; }"

	SNAPSHOT_PILL_IDLE = ("#snapshotPill { background: #2b2f36; border: 1px solid #3a3f46; "
						  "border-radius: 6px; padding: 4px 2px; color: #9aa0a6; }")
	SNAPSHOT_PILL_ACTIVE = ("#snapshotPill { background: #245034; border: 1px solid #2f7f4e; "
							"border-radius: 6px; padding: 4px 2px; color: #e8eaed; "
							"font-weight: bold; }")

	def _on_block_clicked(self, row_index, position):
		"""Selection is display-only; nothing is sent to the device."""
		for key, btn in self._block_buttons.items():
			btn.setChecked(key == (row_index, position))
		block = (self._layout_rows[row_index]['blocks'][position - 1]
				 if row_index < len(self._layout_rows) else None)
		if not block or not block['name']:
			self.block_info_slot.setText('Slot: %s %d — empty' % (
				BLOCK_ROW_NAMES[row_index], position))
			return
		self.block_info_slot.setText('Slot: %s %d — %s (%s)%s' % (
			BLOCK_ROW_NAMES[row_index], position, block['name'],
			block['category'] or '?', '  [bypassed]' if block['bypassed'] else ''))

	def _routing_summary(self, row_index, routing):
		"""One line per row describing how it is reached and where it goes."""
		path_no = 1 if row_index < 2 else 2
		entry = next((r for r in routing if r['path'] == path_no), None)
		if entry is None:
			return ''
		if row_index in (0, 2):
			return 'exit: %s' % (entry.get('upper_exit_name') or '?')
		bits = []
		if entry.get('split_position'):
			bits.append('split @%d' % entry['split_position'])
		if entry.get('merge_position'):
			bits.append('merge @%s' % ('out' if entry['merge_position'] == 9
									   else entry['merge_position']))
		bits.append('exit: %s' % (entry.get('lower_exit_name') or '?'))
		return '  '.join(bits)

	@staticmethod
	def _row_is_live(row_index, routing):
		"""Does signal actually flow along this row?

		Upper rows always carry the path's signal, empty slots or not. A lower
		row only carries signal if the path splits into it, or an upstream
		path fans out to it (exit destination 4).
		"""
		path_no = 1 if row_index < 2 else 2
		entry = next((r for r in routing if r['path'] == path_no), None)
		if row_index in (0, 2):
			return True
		if entry is None:
			return False
		if entry.get('split_position'):
			return True
		return any(other.get('upper_exit') == 4 or other.get('lower_exit') == 4
				   for other in routing if other['path'] < path_no)

	def _on_preset_layout_changed(self, layout):
		self._layout_rows = layout.get('rows', []) if layout else []
		routing = layout.get('routing', []) if layout else []
		for row_index, row in enumerate(self._layout_rows):
			live = self._row_is_live(row_index, routing)
			for link in self._row_connectors.get(row_index, []):
				link.setStyleSheet(self.LINK_LIVE if live else self.LINK_DEAD)
			for block in row['blocks']:
				btn = self._block_buttons.get((row_index, block['position']))
				if btn is None:
					continue
				if not block['name']:
					btn.setText('')
					btn.setToolTip('%s %d — empty' % (BLOCK_ROW_NAMES[row_index],
													  block['position']))
					btn.setStyleSheet(self.STYLE_EMPTY_ACTIVE if live else self.STYLE_EMPTY)
					continue
				short = block['name'].split(',')[0]
				btn.setText(short[:16])
				btn.setToolTip('%s (%s)%s' % (block['name'], block['category'] or '?',
											  '  [bypassed]' if block['bypassed'] else ''))
				colour = self._slot_color_for_category(block['category'])
				if block['bypassed']:
					btn.setStyleSheet(self.STYLE_BYPASSED % colour)
				else:
					btn.setStyleSheet(self.STYLE_BLOCK % colour)
		for row_index, label in self._row_routing_labels.items():
			label.setText(self._routing_summary(row_index, routing))
			live = self._row_is_live(row_index, routing)
			caption = self._row_captions.get(row_index)
			if caption is not None:
				caption.setStyleSheet('color: %s;' % ('#c8ccd2' if live else '#5a6068'))
		self._append_status('Preset layout updated')

	def _refresh_snapshot_pills(self):
		names = self.bridge.helix.snapshot_names
		active = self.bridge.helix.current_snapshot
		for idx, pill in enumerate(self.snapshot_labels):
			number = idx + 1
			label = names[idx] if idx < len(names) else 'SNAPSHOT {}'.format(number)
			pill.setText('{}. {}'.format(number, label))
			pill.setToolTip('Snapshot {}: {}'.format(number, label))
			pill.setStyleSheet(self.SNAPSHOT_PILL_ACTIVE if number == active
							   else self.SNAPSHOT_PILL_IDLE)

	def _on_snapshot_changed(self, snapshot_no):
		self._refresh_snapshot_pills()
		self._append_status('Snapshot {}'.format(snapshot_no))

	def _on_snapshot_names_changed(self, _names):
		self._refresh_snapshot_pills()

	def _on_setlist_names_changed(self, _names):
		self._refresh_setlist_caption()

	def _refresh_setlist_caption(self):
		current = self.bridge.helix.current_setlist
		if current is None:
			self.preset_header.setText('Presets')
			return
		self.preset_header.setText('Presets — %s' % self.bridge.helix.setlist_label(current))

	def _on_preset_names_changed(self, preset_names):
		normalized_names = normalize_preset_names(preset_names)

		self.preset_list.clear()
		for idx, name in enumerate(normalized_names):
			item = QListWidgetItem(f"{idx:03d}: {name}")
			item.setData(Qt.ItemDataRole.UserRole, idx)
			self.preset_list.addItem(item)
		self._sync_current_preset_selection(scroll_to_top=True)
		self._append_status(f"Loaded {len(normalized_names)} presets")

	def _on_preset_no_changed(self, preset_no):
		self._sync_current_preset_selection(scroll_to_top=False)

	def _sync_current_preset_selection(self, scroll_to_top):
		preset_no = self.bridge.helix.current_preset_no
		if not (0 <= preset_no <= HelixUsb.MIDI_PROGRAM_MAX):
			preset_no = self.bridge.helix.preset_no
		if not (0 <= preset_no <= HelixUsb.MIDI_PROGRAM_MAX):
			return

		for row in range(self.preset_list.count()):
			item = self.preset_list.item(row)
			if item.data(Qt.ItemDataRole.UserRole) == preset_no:
				self.preset_list.setCurrentRow(row)
				if scroll_to_top:
					self.preset_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtTop)
				break

	def _on_preset_double_clicked(self, item):
		preset_no = item.data(Qt.ItemDataRole.UserRole)
		if preset_no is None:
			QMessageBox.warning(self, "Preset Selection", "This preset item has no program number.")
			return
		self.bridge.select_preset(int(preset_no))
		self.bridge.request_current_preset_data()

	def _slot_color_for_category(self, category):
		if category is None:
			return "#2d3239"
		color_name = self.bridge.helix.MODULE_COLORS.get(category, "auto_color")
		return COLOR_HEX.get(color_name, "#3f454e")

	def _on_slot_data_changed(self, slot_no, slot_info):
		# Legacy HX Stomp path. HelixUsb.set_slot_info() is never called on the
		# LT -- the block grid is fed by set_preset_layout() instead -- so this
		# is unreachable. Left in place rather than ripped out, but inert.
		return

		display_slot_no = self._slot_index_map.get(slot_no)
		if display_slot_no is None:
			return

		self._slot_info_cache[display_slot_no] = slot_info
		if self._selected_slot_no not in self._slot_info_cache:
			self._selected_slot_no = display_slot_no
		self._refresh_block_strip_visuals()
		self._refresh_selected_block_details()

	def _slot_short_name(self, slot_no):
		slot_info = self._slot_info_cache.get(slot_no)
		if slot_info is None:
			return "-"

		try:
			text = slot_info.to_string()
		except Exception:
			return "?"

		short_text = text.split(':', 1)[-1].strip() if ':' in text else text
		if len(short_text) > 18:
			short_text = short_text[:15] + "..."
		return short_text

	def _module_type_and_name(self, slot_info):
		if slot_info is None:
			return ("Unknown", "-")

		module_id = getattr(slot_info, "module_id", None)
		if module_id is not None:
			entry = module_catalog.get(str(module_id))
			if entry is not None and len(entry) >= 2:
				return (entry[0] or "Unknown", entry[1] or "-")

		try:
			category = slot_info.category() or "Unknown"
		except Exception:
			category = "Unknown"

		try:
			text = slot_info.to_string()
		except Exception:
			text = "-"

		module_name = text.split(':', 1)[-1].strip() if ':' in text else text
		return (category, module_name)

	def _build_slider_specs(self, slot_info):
		specs = []
		if slot_info is None:
			return specs

		param_name_map = self._parameter_name_map(slot_info)

		for key in ("params", "amp_params", "cab_params"):
			values = getattr(slot_info, key, None)
			if isinstance(values, (list, tuple)):
				for idx, value in enumerate(values):
					if not isinstance(value, (int, float)):
						continue
					if 0.0 <= value <= 1.0:
						slider_value = int(value * 100)
					else:
						slider_value = int(max(0, min(100, value)))
					label = param_name_map.get((key, idx), f"{key}.{idx}")
					specs.append((label, slider_value))

		if len(specs) == 0:
			for idx in range(4):
				specs.append((f"setting_{idx + 1}", 50))

		return specs[:10]

	def _parameter_name_map(self, slot_info):
		name_map = {}
		for attr_name, key in (("param_names", "params"), ("amp_param_names", "amp_params"), ("cab_param_names", "cab_params")):
			names = getattr(slot_info, attr_name, None)
			if isinstance(names, (list, tuple)):
				for idx, value in enumerate(names):
					if isinstance(value, str) and value.strip() != "":
						name_map[(key, idx)] = value
		return name_map

	def _module_type_abbrev(self, module_type):
		if module_type in (None, "", "Unknown"):
			return "---"
		if module_type == "Amp+Cab":
			return "A+C"
		parts = module_type.replace('/', ' ').replace('+', ' ').split()
		if len(parts) >= 2:
			return ''.join([p[0] for p in parts[:3]]).upper()
		return module_type[:3].upper()

	def _populate_device_type_list(self):
		self.device_type_list.clear()
		for category in sorted(self.bridge.helix.MODULE_COLORS.keys()):
			self.device_type_list.addItem(category)

	def _populate_module_name_list(self, module_type, selected_name):
		self.module_name_list.clear()
		if module_type is None:
			return

		names = sorted({entry[1] for entry in module_catalog.values() if len(entry) >= 2 and entry[0] == module_type and entry[1]})
		if len(names) == 0 and selected_name not in (None, "", "-"):
			names = [selected_name]

		selected_row = -1
		for idx, name in enumerate(names):
			self.module_name_list.addItem(name)
			if name == selected_name:
				selected_row = idx

		if selected_row >= 0:
			self.module_name_list.setCurrentRow(selected_row)

	def _set_selected_slot(self, slot_no, source):
		# Legacy HX Stomp path, no longer wired to anything. It called
		# highlight_slot(), which writes to the device, so it must stay
		# unreachable rather than merely unused.
		return

		if source == "ui":
			try:
				self.bridge.helix.highlight_slot(slot_no)
			except Exception:
				pass

		self._refresh_block_strip_visuals()
		self._refresh_selected_block_details()

	def _refresh_block_strip_visuals(self):
		for slot_no, btn in self._slot_button_widgets.items():
			btn.blockSignals(True)
			btn.setChecked(slot_no == self._selected_slot_no)
			btn.blockSignals(False)

			slot_info = self._slot_info_cache.get(slot_no)
			module_type, _ = self._module_type_and_name(slot_info)
			icon = ICON_BY_CATEGORY.get(module_type, "◼")
			btn.setText(icon)

			try:
				category = slot_info.category() if slot_info is not None else None
			except Exception:
				category = None

			bg = self._slot_color_for_category(category)
			type_label = self._slot_type_label_widgets.get(slot_no)
			if type_label is not None:
				type_label.setText(self._module_type_abbrev(module_type))
				type_label.setStyleSheet(f"#slotTypeLabel {{ color: {bg}; }}")

			btn.setStyleSheet(
				f"#slotButton {{ background-color: {bg}; border: 1px solid #3a3f46; border-radius: 6px; padding: 4px 6px; }}"
				"#slotButton:checked { border: 1px solid #d6923c; }"
			)

	def _refresh_selected_block_details(self):
		slot_no = self._selected_slot_no
		slot_info = self._slot_info_cache.get(slot_no)
		self.block_info_slot.setText(f"Slot: {slot_no:02d}")

		if slot_info is None:
			self.device_type_list.clearSelection()
			self.module_name_list.clear()
			self._render_settings_sliders([])
			return

		module_type, module_name = self._module_type_and_name(slot_info)
		for row in range(self.device_type_list.count()):
			item = self.device_type_list.item(row)
			if item.text() == module_type:
				self.device_type_list.setCurrentRow(row)
				break

		self._populate_module_name_list(module_type, module_name)
		self._render_settings_sliders(self._build_slider_specs(slot_info))

	def _render_settings_sliders(self, slider_specs):
		while self.module_settings_layout.count():
			item = self.module_settings_layout.takeAt(0)
			widget = item.widget()
			if widget is not None:
				widget.deleteLater()

		if len(slider_specs) == 0:
			empty = QLabel("No settings available")
			self.module_settings_layout.addWidget(empty)
			return

		for label_text, slider_value in slider_specs:
			row = QWidget()
			row_layout = QHBoxLayout(row)
			row_layout.setContentsMargins(0, 0, 0, 0)
			row_layout.setSpacing(8)

			name_label = QLabel(label_text)
			name_label.setMinimumWidth(96)
			value_label = QLabel(str(slider_value))
			value_label.setMinimumWidth(34)

			slider = QSlider(Qt.Orientation.Horizontal)
			slider.setRange(0, 100)
			slider.setValue(slider_value)
			slider.valueChanged.connect(lambda v, vl=value_label: vl.setText(str(v)))

			row_layout.addWidget(name_label)
			row_layout.addWidget(slider, 1)
			row_layout.addWidget(value_label)
			self.module_settings_layout.addWidget(row)

		self.module_settings_layout.addStretch()


def _install_signal_handlers(app):
	"""Make SIGTERM and SIGINT quit the Qt event loop cleanly.

	`timeout N python helix_qt_ui.py` sends SIGTERM, which without this
	killed the process outright: HelixUsb.shutdown() never ran, USB
	interfaces were never released, and the device then failed to serve the
	next run for several seconds.

	The keep-alive timer exists because Python-level signal handlers only run
	between bytecodes, and while app.exec() is blocked in C++ no Python
	executes. Firing a no-op timer periodically gives the interpreter the
	chance to notice the signal.
	"""
	def handler(signum, _frame):
		log.info('Received %s; shutting down', signal.Signals(signum).name)
		app.quit()

	for sig in (signal.SIGINT, signal.SIGTERM):
		signal.signal(sig, handler)

	keep_alive = QTimer()
	keep_alive.setInterval(200)
	keep_alive.timeout.connect(lambda: None)
	keep_alive.start()
	return keep_alive


def main(argv=None):
	if argv is None:
		argv = sys.argv

	logging.basicConfig(
		level='INFO',
		format="%(asctime)s - %(levelname)s - %(message)s (%(name)s)",
		datefmt="%Y-%m-%d %H:%M:%S"
	)

	app = QApplication(argv)
	window = MainWindow()
	window.show()

	# Held in a local so the timer is not garbage collected mid-run.
	_keep_alive = _install_signal_handlers(app)

	try:
		return app.exec()
	finally:
		# app.quit() does not deliver closeEvent, so the teardown that the
		# window would have done has to happen here too. Bridge.stop() is
		# idempotent, so the normal window-close path is unaffected.
		window.bridge.stop()


if __name__ == '__main__':
	raise SystemExit(main(sys.argv))
