  // ---------- init ----------
  renderTiles();
  refreshQuotes();
  fitHomeTreemapHeight();
  loadIndices().then(fitHomeTreemapHeight); // 指數列非同步載入完會改變上方高度，載完要重新量一次
  loadHomeTreemap();
  monitorHealth();
  setInterval(refreshQuotes, 15000);
  setInterval(loadIndices, 15000);
  setInterval(loadHomeTreemap, 60000);
  setInterval(monitorHealth, 20000);
})();
