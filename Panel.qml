import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "anders.appletv-remote"
  ipcTarget: "anders.appletv-remote"
  manageIpc: false

  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") || (home + "/.config")
  readonly property string pluginDir: configHome + "/omarchy/plugins/anders.appletv-remote"
  readonly property string backend: pluginDir + "/bin/apple-tv"
  readonly property string setupScript: pluginDir + "/bin/setup"
  readonly property string identifier: String(setting("identifier", "") || "")
  readonly property var activeDevice: findActiveDevice()
  readonly property string activeIdentifier: activeDevice ? String(activeDevice.identifier) : ""
  readonly property string activeAddress: activeDevice ? String(activeDevice.address) : ""
  readonly property bool maskTextPreview: Boolean(setting("maskTextPreview", false))
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property string statusText: "Ready"
  property string lastError: ""
  property var devices: []
  property bool discovering: false
  property string lastStroke: "—"
  property string lastAction: "Waiting for a key"
  property bool textInputActive: false
  property string typedPreview: ""
  property var commandQueue: []
  property string runningCommand: ""

  function findActiveDevice() {
    if (devices.length === 1 && identifier === "") return devices[0]
    for (var index = 0; index < devices.length; ++index) {
      var device = devices[index]
      if (String(device.identifier) === identifier || String(device.address) === identifier) return device
    }
    return null
  }

  function displayedPreview() {
    return maskTextPreview ? "•".repeat(typedPreview.length) : typedPreview
  }

  function migrateLegacyIdentifier() {
    if (!activeDevice || !bar || !bar.shell) return
    if (identifier === String(activeDevice.address)) {
      bar.shell.updateEntryInline(moduleName, {
        id: moduleName,
        identifier: String(activeDevice.deviceIdentifier),
        maskTextPreview: maskTextPreview
      })
    }
  }

  function command(name) {
    if (activeAddress === "") {
      statusText = devices.length > 1 ? "Choose an Apple TV" : "No Apple TV found"
      return
    }
    lastError = ""
    commandQueue = commandQueue.concat([name])
    runNextCommand()
  }

  function runNextCommand() {
    if (action.running || commandQueue.length === 0 || activeAddress === "") return
    runningCommand = commandQueue[0]
    commandQueue = commandQueue.slice(1)
    action.command = [backend, activeAddress, runningCommand]
    action.running = true
  }

  function sendStroke(stroke, actionName, commandName) {
    lastStroke = stroke
    lastAction = actionName
    command(commandName)
  }

  function sendText(text) {
    lastStroke = text === " " ? "SPACE" : text
    lastAction = "Text sent to Apple TV"
    typedPreview += text
    previewClear.restart()
    command("text_append:" + text)
  }

  function sendTextBackspace() {
    lastStroke = "BACKSPACE"
    lastAction = "Text updated on Apple TV"
    if (typedPreview.length > 0) typedPreview = typedPreview.slice(0, -1)
    previewClear.restart()
    command("text_backspace")
  }

  function pollKeyboardState() {
    if (!opened || focusState.running || activeAddress === "") return
    focusState.command = [backend, activeAddress, "keyboard_watch"]
    focusState.running = true
  }

  function setup() {
    if (activeAddress === "") {
      statusText = devices.length > 1 ? "Choose an Apple TV first" : "No Apple TV found"
      return
    }
    Quickshell.execDetached(["omarchy", "launch", "terminal", setupScript, activeAddress])
    close()
  }

  function refresh() {
    if (discover.running) return
    discovering = true
    discover.running = true
  }

  function refreshStatus() {
    if (status.running || activeAddress === "") return
    status.command = [backend, activeAddress, "power_state"]
    status.running = true
  }

  function selectDevice(device) {
    if (!device || !bar || !bar.shell) return
    var entry = { id: moduleName, identifier: String(device.deviceIdentifier), maskTextPreview: maskTextPreview }
    bar.shell.updateEntryInline(moduleName, entry)
    statusText = "Selected " + device.name
    Qt.callLater(refreshStatus)
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Component.onCompleted: refresh()

  onOpenedChanged: {
    if (opened) {
      lastStroke = "—"
      lastAction = "Waiting for a key"
      typedPreview = ""
      textInputActive = false
      refresh()
      pollKeyboardState()
      Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    } else {
      focusState.running = false
      textInputActive = false
      commandQueue = []
    }
  }

  onActiveAddressChanged: {
    focusState.running = false
    textInputActive = false
    if (opened && activeAddress !== "") Qt.callLater(pollKeyboardState)
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function up(): string { root.command("up"); return "ok" }
    function down(): string { root.command("down"); return "ok" }
    function left(): string { root.command("left"); return "ok" }
    function right(): string { root.command("right"); return "ok" }
    function select(): string { root.command("select"); return "ok" }
    function menu(): string { root.command("menu"); return "ok" }
    function home(): string { root.command("home"); return "ok" }
    function playPause(): string { root.command("play_pause"); return "ok" }
    function power(): string { root.command("turn_off"); return "ok" }
    function status(): string { return root.statusText }
  }

  Process {
    id: discover
    command: [root.pluginDir + "/bin/discover"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var result = JSON.parse(text.trim() || "{}")
          root.devices = result.devices || []
          root.lastError = result.error || ""
          root.migrateLegacyIdentifier()
          if (root.devices.length === 0) root.statusText = result.error || "No Apple TV found"
          else if (root.devices.length > 1 && !root.activeDevice) root.statusText = "Choose an Apple TV"
          else root.refreshStatus()
        } catch (error) {
          root.devices = []
          root.lastError = "Could not read discovery results"
        }
      }
    }
    onExited: function(exitCode) {
      root.discovering = false
      if (exitCode === 127) root.statusText = "Setup required"
      else if (exitCode !== 0 && root.lastError === "") root.statusText = "Discovery failed"
    }
  }

  Process {
    id: action
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.lastError = text.trim().split("\n").pop()
    }
    onExited: function(exitCode) {
      root.statusText = exitCode === 0 ? "Command sent" : "Could not reach Apple TV"
      if (exitCode === 127) root.statusText = "Setup required"
      root.runningCommand = ""
      Qt.callLater(root.runNextCommand)
    }
  }

  Process {
    id: focusState
    stdout: SplitParser {
      onRead: function(line) {
        try {
          var result = JSON.parse(String(line).trim() || "{}")
          root.textInputActive = result.keyboard === "Focused"
        } catch (error) {
          root.lastError = "Could not read keyboard state"
        }
      }
    }
    stderr: SplitParser {
      onRead: function(line) {
        if (String(line).trim() !== "") root.lastError = String(line).trim()
      }
    }
    onExited: function(exitCode) {
      root.textInputActive = false
      if (root.opened && root.activeAddress !== "" && exitCode !== 127) focusRetry.restart()
    }
  }

  Timer { id: focusRetry; interval: 1500; repeat: false; onTriggered: root.pollKeyboardState() }

  Timer {
    id: previewClear
    interval: 1800
    repeat: false
    onTriggered: {
      root.typedPreview = ""
      root.lastStroke = "—"
      root.lastAction = root.textInputActive ? "Waiting for text" : "Waiting for a key"
    }
  }

  Process {
    id: status
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var value = text.trim()
        if (value.indexOf("On") >= 0) root.statusText = "Apple TV is on"
        else if (value.indexOf("Off") >= 0) root.statusText = "Apple TV is off"
        else if (value !== "") root.statusText = value
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.lastError = text.trim().split("\n").pop()
    }
    onExited: function(exitCode) {
      if (exitCode === 127) root.statusText = "Setup required"
      else if (exitCode !== 0 && root.devices.length > 0) root.statusText = "Pairing required"
      else if (exitCode !== 0) root.statusText = "Apple TV unavailable"
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: "Apple TV Remote"
    iconComponent: Component {
      RemoteIcon {
        anchors.centerIn: parent
        width: Style.space(9)
        height: Style.space(16)
        color: root.foreground
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.command("play_pause")
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(330))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    FocusScope {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (!root.opened) return
        if (event.key === Qt.Key_Escape) root.close()
        else if (event.key === Qt.Key_Left) root.sendStroke("←", "Left", "left")
        else if (event.key === Qt.Key_Right) root.sendStroke("→", "Right", "right")
        else if (event.key === Qt.Key_Up) root.sendStroke("↑", "Up", "up")
        else if (event.key === Qt.Key_Down) root.sendStroke("↓", "Down", "down")
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) root.sendStroke("ENTER", "Select", "select")
        else if (event.key === Qt.Key_Backspace && root.textInputActive) root.sendTextBackspace()
        else if (event.key === Qt.Key_Backspace) root.sendStroke("BACKSPACE", "Back / Menu", "menu")
        else if (event.key === Qt.Key_Space && root.textInputActive) root.sendText(" ")
        else if (event.key === Qt.Key_Space) root.sendStroke("SPACE", "Play / Pause", "play_pause")
        else if (root.textInputActive && event.text && event.text.length > 0
                 && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) root.sendText(event.text)
        else if (event.key === Qt.Key_H) root.sendStroke("H", "Home", "home")
        else if (event.text === "+" || event.key === Qt.Key_Plus) root.sendStroke("+", "Volume up", "volume_up")
        else if (event.text === "-" || event.key === Qt.Key_Minus) root.sendStroke("−", "Volume down", "volume_down")
        else return
        event.accepted = true
      }

      Column {
        id: content
        width: parent.width
        spacing: Style.space(14)

        PanelHero {
          width: parent.width
          title: "Apple TV"
          meta: root.textInputActive ? "TYPE ON YOUR KEYBOARD" : root.statusText.toUpperCase()
          foreground: root.foreground
          fontFamily: root.fontFamily
          iconComponent: Component {
            RemoteIcon {
              width: Style.space(18)
              height: Style.space(34)
              color: root.foreground
            }
          }
        }

        Text {
          visible: root.lastError !== ""
          width: parent.width
          text: root.lastError
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Column {
          visible: root.devices.length > 0
          width: parent.width
          spacing: Style.space(7)

          PanelSectionHeader {
            text: "APPLE TVs"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          Repeater {
            model: root.devices
            Button {
              required property var modelData
              width: parent.width
              text: String(modelData.name) + "  ·  " + String(modelData.address)
              iconText: "󰟴"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              active: root.activeIdentifier === String(modelData.identifier)
              onClicked: root.selectDevice(modelData)
            }
          }
        }

        Rectangle {
          width: parent.width
          implicitHeight: keyFeedback.implicitHeight + Style.space(28)
          radius: Style.cornerRadius
          color: Style.selectedFillFor(root.foreground, Color.accent)

          Column {
            id: keyFeedback
            anchors.centerIn: parent
            spacing: Style.space(4)

            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              width: Math.max(0, keyFeedback.parent.width - Style.space(28))
              text: root.textInputActive && root.typedPreview !== "" ? root.displayedPreview() : root.lastStroke
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.displayLarge
              font.bold: true
              horizontalAlignment: Text.AlignHCenter
              elide: Text.ElideLeft
            }
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.lastAction.toUpperCase()
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.1
            }
          }
        }

        PanelSeparator { foreground: root.foreground }

        Column {
          width: parent.width
          spacing: Style.space(8)

          PanelSectionHeader {
            text: "KEYBOARD REMOTE"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          ShortcutRow { keys: "←  ↑  ↓  →"; action: "Navigate" }
          ShortcutRow { keys: "ENTER"; action: "Select" }
          ShortcutRow { keys: "BACKSPACE"; action: "Back / Menu" }
          ShortcutRow { keys: "SPACE"; action: "Play / Pause" }
          ShortcutRow { keys: "H"; action: "Home" }
          ShortcutRow { keys: "+  /  −"; action: "Volume" }
          ShortcutRow { keys: "ESC"; action: "Close remote" }

          Text {
            visible: root.textInputActive
            width: parent.width
            text: "Text field detected · printable keys and Backspace are sent directly"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
            wrapMode: Text.WordWrap
          }
        }

        Button {
          width: parent.width
          text: root.statusText === "Setup required" ? "Install and pair Apple TV" : "Pair or change Apple TV"
          iconText: "󰒓"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          active: true
          onClicked: root.setup()
        }

      }
    }
  }

  component ShortcutRow: Row {
    required property string keys
    required property string action
    width: parent.width
    spacing: Style.space(10)

    Text {
      width: parent.width * 0.42
      text: keys
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.bold: true
    }
    Text {
      width: parent.width * 0.58 - parent.spacing
      text: action
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
    }
  }

  component RemoteIcon: Item {
    id: remoteIcon
    property color color: root.foreground

    Rectangle {
      id: tintLayer
      anchors.fill: remoteSvg
      color: remoteIcon.color
      visible: false
      layer.enabled: true
    }

    Image {
      id: remoteSvg
      anchors.fill: parent
      source: root.pluginDir + "/assets/siri-remote.svg"
      fillMode: Image.PreserveAspectFit
      sourceSize.width: Math.max(32, Math.round(width * 3))
      sourceSize.height: Math.max(32, Math.round(height * 3))
      visible: false
      layer.enabled: true
    }

    MultiEffect {
      anchors.fill: remoteSvg
      source: tintLayer
      maskEnabled: true
      maskSource: remoteSvg
      maskThresholdMin: 0.01
      maskSpreadAtMin: 0.01
    }
  }
}
