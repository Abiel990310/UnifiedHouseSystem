/**
 * WebSocket client with auto-reconnect.
 * Dispatches a custom 'ruview-update' event on window with parsed data.
 */

(function () {
  let _ws = null;
  let _reconnectDelay = 1000;
  let _reconnectTimer = null;
  let _connected = false;

  function connect() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${location.host}/ws`;

    _ws = new WebSocket(url);

    _ws.onopen = () => {
      _connected = true;
      _reconnectDelay = 1000;
      clearTimeout(_reconnectTimer);
      window.dispatchEvent(new CustomEvent("ruview-connected"));
    };

    _ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        window.dispatchEvent(new CustomEvent("ruview-update", { detail: data }));
      } catch (e) {
        console.warn("WS parse error:", e);
      }
    };

    _ws.onclose = () => {
      _connected = false;
      window.dispatchEvent(new CustomEvent("ruview-disconnected"));
      _reconnectTimer = setTimeout(() => {
        _reconnectDelay = Math.min(_reconnectDelay * 2, 30000);
        connect();
      }, _reconnectDelay);
    };

    _ws.onerror = () => {
      _ws.close();
    };
  }

  connect();

  window.RuViewWS = {
    isConnected: () => _connected,
  };
})();
