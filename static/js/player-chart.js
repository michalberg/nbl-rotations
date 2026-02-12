/**
 * NBL Rotations - Player season chart (D3.js)
 *
 * Shows all games for a player as rows (newest on top).
 * Layout: game info (date + opponent) | minutes | minute blocks
 */

(function () {
  const CELL_W = 16;
  const CELL_H = 22;
  const CELL_GAP_X = 1;
  const CELL_GAP_Y = 2;
  const CELL_STEP_X = CELL_W + CELL_GAP_X;
  const CELL_STEP_Y = CELL_H + CELL_GAP_Y;
  const PERIOD_GAP = 6;
  const HEADER_HEIGHT = 20;

  const INFO_WIDTH = 210;
  const GAP_AFTER_INFO = 6;
  const MINUTES_LABEL_WIDTH = 42;
  const GAP_AFTER_MINUTES = 8;
  const LEFT_OFFSET = INFO_WIDTH + GAP_AFTER_INFO + MINUTES_LABEL_WIDTH + GAP_AFTER_MINUTES;

  const TEAM_COLOR = "#8B1A1A";

  function formatMMSS(totalSeconds) {
    const m = Math.floor(totalSeconds / 60);
    const s = Math.round(totalSeconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function formatDate(dateStr) {
    if (!dateStr) return "";
    const parts = dateStr.split("-");
    return `${parseInt(parts[2])}.${parseInt(parts[1])}.`;
  }

  function minuteToX(minute, periods) {
    let x = 0;
    let accumulated = 0;
    for (const p of periods) {
      const periodMinutes = p.endMinute - p.startMinute;
      if (minute < accumulated + periodMinutes) {
        x += (minute - accumulated) * CELL_STEP_X;
        return x;
      }
      x += periodMinutes * CELL_STEP_X + PERIOD_GAP;
      accumulated += periodMinutes;
    }
    return x;
  }

  function totalChartWidth(periods) {
    let w = 0;
    for (let i = 0; i < periods.length; i++) {
      const p = periods[i];
      w += (p.endMinute - p.startMinute) * CELL_STEP_X;
      if (i < periods.length - 1) w += PERIOD_GAP;
    }
    return w;
  }

  function maxPeriods(games) {
    let best = [
      { period: 1, label: "Q1", startMinute: 0, endMinute: 10, duration: 10 },
      { period: 2, label: "Q2", startMinute: 10, endMinute: 20, duration: 10 },
      { period: 3, label: "Q3", startMinute: 20, endMinute: 30, duration: 10 },
      { period: 4, label: "Q4", startMinute: 30, endMinute: 40, duration: 10 },
    ];
    for (const g of games) {
      if (g.periods && g.periods.length > best.length) {
        best = g.periods;
      }
    }
    return best;
  }

  function renderPlayerChart(containerId, data) {
    const container = d3.select(containerId);
    const games = data.games.slice().reverse();
    const numGames = games.length;
    if (numGames === 0) return;

    const periods = maxPeriods(games);
    const chartW = totalChartWidth(periods);

    const chartH = HEADER_HEIGHT + numGames * CELL_STEP_Y + 20;
    const svgW = LEFT_OFFSET + chartW + 4;
    const svgH = chartH + 10;

    const svg = container
      .append("svg")
      .attr("width", svgW)
      .attr("height", svgH)
      .attr("viewBox", `0 0 ${svgW} ${svgH}`);

    // Clip path to prevent info text overflow
    svg.append("defs").append("clipPath")
      .attr("id", "info-clip")
      .append("rect")
      .attr("x", 0)
      .attr("y", 0)
      .attr("width", INFO_WIDTH)
      .attr("height", svgH);

    const g = svg.append("g").attr("transform", `translate(${LEFT_OFFSET}, ${HEADER_HEIGHT})`);

    // Period labels at top
    periods.forEach((p) => {
      const startX = minuteToX(p.startMinute, periods);
      const endX = minuteToX(p.endMinute - 1, periods) + CELL_W;
      const centerX = (startX + endX) / 2;

      g.append("text")
        .attr("x", centerX)
        .attr("y", -8)
        .attr("text-anchor", "middle")
        .attr("fill", "#555")
        .attr("font-size", "9px")
        .text(p.label);
    });

    // Draw each game row
    games.forEach((game, gameIdx) => {
      const y = gameIdx * CELL_STEP_Y;
      const rowCenterY = HEADER_HEIGHT + y + CELL_H / 2;

      // --- Game info (left, clipped) ---
      const homeAway = game.isHome ? "vs" : "@";
      const infoText = `${formatDate(game.date)} ${homeAway} ${game.opponent}`;

      const infoGroup = svg.append("g")
        .attr("clip-path", "url(#info-clip)");

      const link = infoGroup.append("a")
        .attr("href", `../../game/${game.gameId}.html`);

      link.append("text")
        .attr("x", 4)
        .attr("y", rowCenterY)
        .attr("text-anchor", "start")
        .attr("dominant-baseline", "central")
        .attr("fill", "#6a9fd8")
        .attr("font-size", "11px")
        .text(infoText);

      // --- Minutes label / DNP ---
      const minutesX = INFO_WIDTH + GAP_AFTER_INFO + MINUTES_LABEL_WIDTH - 4;
      if (game.isDNP) {
        svg.append("text")
          .attr("x", minutesX)
          .attr("y", rowCenterY)
          .attr("text-anchor", "end")
          .attr("dominant-baseline", "central")
          .attr("fill", "#666")
          .attr("font-size", "10px")
          .text("DNP");
      } else {
        svg.append("text")
          .attr("x", minutesX)
          .attr("y", rowCenterY)
          .attr("text-anchor", "end")
          .attr("dominant-baseline", "central")
          .attr("fill", "#999")
          .attr("font-size", "11px")
          .attr("font-weight", "bold")
          .text(formatMMSS(game.totalSeconds));
      }

      // --- Minute blocks ---
      (game.minutes || []).forEach((min) => {
        if (!min.onCourt) return;

        const x = minuteToX(min.minute, periods);
        const pct = min.onCourtSeconds / 60;
        const opacity = min.fullMinute ? 1.0 : pct <= 0.25 ? 0.3 : pct <= 0.5 ? 0.5 : pct <= 0.75 ? 0.7 : 0.85;

        const block = g.append("g")
          .attr("class", "minute-block")
          .on("mouseenter", function (event) {
            showTooltip(event, data, game, min);
          })
          .on("mousemove", function (event) {
            moveTooltip(event);
          })
          .on("mouseleave", function () {
            hideTooltip();
          });

        block.append("rect")
          .attr("x", x)
          .attr("y", y)
          .attr("width", CELL_W)
          .attr("height", CELL_H)
          .attr("rx", 2)
          .attr("fill", TEAM_COLOR)
          .attr("opacity", opacity);

        if (min.pts > 0) {
          block.append("text")
            .attr("x", x + CELL_W / 2)
            .attr("y", y + CELL_H / 2)
            .attr("text-anchor", "middle")
            .attr("dominant-baseline", "central")
            .attr("fill", "#fff")
            .attr("font-size", "9px")
            .attr("font-weight", "bold")
            .attr("pointer-events", "none")
            .text(min.pts);
        }
      });
    });
  }

  // Tooltip
  const tooltip = d3.select("#tooltip");

  function showTooltip(event, playerData, game, minuteData) {
    const minute = minuteData.minute;
    const s = minuteData.stats || {};
    const gs = game.gameStats || {};

    const pm = minuteData.plusMinus;
    const pmClass = pm > 0 ? "positive" : pm < 0 ? "negative" : "";
    const pmStr = pm > 0 ? `+${pm}` : `${pm}`;

    const pct = Math.round((minuteData.onCourtSeconds / 60) * 100);
    const coverageStr = pct >= 100
      ? "cel\u00e1 minuta"
      : `${minuteData.onCourtSeconds}s z 60s (${pct}%)`;

    let html = `<div class="player-name">${playerData.firstName} ${playerData.familyName}</div>`;
    html += `<div class="detail">${game.opponent} (${game.score})</div>`;
    html += `<div class="detail">Minuta: ${minute + 1} \u00b7 Na h\u0159i\u0161ti: ${coverageStr}</div>`;
    html += `<div class="detail ${pmClass}">+/\u2212: ${pmStr}</div>`;

    const lines = [];
    if (s.pts)  lines.push(`PTS ${s.pts}`);
    if (s.fga)  lines.push(`FG ${s.fgm}/${s.fga}`);
    if (s.fg3a) lines.push(`3PT ${s.fg3m}/${s.fg3a}`);
    if (s.fta)  lines.push(`FT ${s.ftm}/${s.fta}`);
    if (s.reb)  lines.push(`REB ${s.reb}`);
    if (s.ast)  lines.push(`AST ${s.ast}`);
    if (s.stl)  lines.push(`STL ${s.stl}`);
    if (s.blk)  lines.push(`BLK ${s.blk}`);
    if (s.tov)  lines.push(`TOV ${s.tov}`);
    if (s.pf)   lines.push(`PF ${s.pf}`);

    if (lines.length > 0) {
      html += lines.map(l => `<div class="detail stats">${l}</div>`).join("");
    }

    const gamePm = game.totalPlusMinus || 0;
    const gamePmStr = gamePm > 0 ? `+${gamePm}` : `${gamePm}`;
    html += `<div class="detail stats">Z\u00e1pas: ${gs.pts || 0} PTS, ${gs.reb || 0} REB, ${gs.ast || 0} AST (${gamePmStr})</div>`;

    tooltip.html(html).style("display", "block");
    moveTooltip(event);
  }

  function moveTooltip(event) {
    const ttNode = tooltip.node();
    const ttW = ttNode.offsetWidth;
    const ttH = ttNode.offsetHeight;
    let x = event.clientX + 12;
    let y = event.clientY - 10;

    if (x + ttW > window.innerWidth - 10) {
      x = event.clientX - ttW - 12;
    }
    if (y + ttH > window.innerHeight - 10) {
      y = event.clientY - ttH - 10;
    }

    tooltip.style("left", x + "px").style("top", y + "px");
  }

  function hideTooltip() {
    tooltip.style("display", "none");
  }

  function init() {
    d3.json(PLAYER_DATA_URL).then((data) => {
      renderPlayerChart("#player-chart", data);
    });
  }

  init();
})();
