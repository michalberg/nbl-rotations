/**
 * NBL Rotations - D3.js visualization
 *
 * Block color meaning:
 * - Full opacity: player was on court for the full minute
 * - Graduated opacity (0.25/0.5/0.75): partial minute on court
 * - No block: player was on the bench
 *
 * Bottom row: team +/- per minute (green = positive, magenta = negative)
 */

(function () {
  const CELL_W = 16;
  const CELL_H = 26;
  const CELL_GAP_X = 1;
  const CELL_GAP_Y = 2;
  const CELL_STEP_X = CELL_W + CELL_GAP_X;
  const CELL_STEP_Y = CELL_H + CELL_GAP_Y;
  const PERIOD_GAP = 6;
  const NAME_WIDTH = 95;
  const MINUTES_LABEL_WIDTH = 40;
  const HEADER_HEIGHT = 20;
  const STARTER_SEPARATOR = 2;
  const STAT_COL_W = 26;
  const STAT_FONT = "10px";

  // Box score columns: key, label, formatter
  const BOX_COLS = [
    { key: "pts",  label: "PTS",  fmt: (s) => s.pts },
    { key: "reb",  label: "REB",  fmt: (s) => s.reb },
    { key: "ast",  label: "AST",  fmt: (s) => s.ast },
    { key: "stl",  label: "STL",  fmt: (s) => s.stl },
    { key: "blk",  label: "BLK",  fmt: (s) => s.blk },
    { key: "fg",   label: "FG",   fmt: (s) => `${s.fgm}/${s.fga}` },
    { key: "fg3",  label: "3PT",  fmt: (s) => `${s.fg3m}/${s.fg3a}` },
    { key: "ft",   label: "FT",   fmt: (s) => `${s.ftm}/${s.fta}` },
    { key: "tov",  label: "TO",   fmt: (s) => s.tov },
    { key: "pf",   label: "PF",   fmt: (s) => s.pf },
    { key: "pm",   label: "+/−",  fmt: null }, // special: uses totalPlusMinus
  ];

  const BOX_TABLE_WIDTH = BOX_COLS.length * STAT_COL_W;

  // Team colors
  const TEAM_COLORS = {
    1: "#8B1A1A",
    2: "#1A3A8B",
  };

  const PM_POSITIVE_COLOR = "#4caf50";
  const PM_NEGATIVE_COLOR = "#e040fb";

  function formatMMSS(totalSeconds) {
    const m = Math.floor(totalSeconds / 60);
    const s = Math.round(totalSeconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
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

  function renderTeamChart(containerId, data, teamKey) {
    const container = d3.select(containerId);
    const teamData = data.players[teamKey];
    const periods = data.periods;
    const teamPM = data.teamPlusMinus[teamKey];
    const teamInfo = teamKey === "1" ? data.team1 : data.team2;
    const teamColor = TEAM_COLORS[teamKey];

    const numPlayers = teamData.length;
    const starterCount = teamData.filter((p) => p.isStarter).length;

    const chartW = totalChartWidth(periods);
    const rightStart = MINUTES_LABEL_WIDTH + chartW + 5;
    const nameEnd = rightStart + NAME_WIDTH;
    const tableStart = nameEnd + 2;

    const chartH =
      HEADER_HEIGHT +
      numPlayers * CELL_STEP_Y +
      STARTER_SEPARATOR +
      CELL_H + // +/- row
      30; // period labels

    const svgW = tableStart + BOX_TABLE_WIDTH + 4;
    const svgH = chartH + 10;

    // Team header
    container
      .append("div")
      .attr("class", "team-header")
      .text(`${teamInfo.name} (${teamInfo.score})`);

    const svg = container
      .append("svg")
      .attr("width", svgW)
      .attr("height", svgH)
      .attr("viewBox", `0 0 ${svgW} ${svgH}`);

    const g = svg.append("g").attr("transform", `translate(${MINUTES_LABEL_WIDTH}, ${HEADER_HEIGHT})`);

    // --- Box score column headers ---
    BOX_COLS.forEach((col, ci) => {
      svg.append("text")
        .attr("x", tableStart + ci * STAT_COL_W + STAT_COL_W / 2)
        .attr("y", HEADER_HEIGHT - 6)
        .attr("text-anchor", "middle")
        .attr("fill", "#666")
        .attr("font-size", "9px")
        .attr("font-weight", "bold")
        .text(col.label);
    });

    // Starter separator line
    const separatorY = starterCount * CELL_STEP_Y;
    g.append("line")
      .attr("x1", -5)
      .attr("x2", chartW)
      .attr("y1", separatorY + STARTER_SEPARATOR / 2)
      .attr("y2", separatorY + STARTER_SEPARATOR / 2)
      .attr("stroke", "#555")
      .attr("stroke-dasharray", "4,3")
      .attr("stroke-width", 1);

    // Draw minute blocks for each player
    teamData.forEach((player, playerIdx) => {
      const yOffset = playerIdx >= starterCount ? STARTER_SEPARATOR : 0;
      const y = playerIdx * CELL_STEP_Y + yOffset;
      const rowCenterY = HEADER_HEIGHT + y + CELL_H / 2;

      player.minutes.forEach((min) => {
        if (!min.onCourt) return;

        const x = minuteToX(min.minute, periods);
        const pct = min.onCourtSeconds / 60;
        const opacity = min.fullMinute ? 1.0 : pct <= 0.25 ? 0.3 : pct <= 0.5 ? 0.5 : pct <= 0.75 ? 0.7 : 0.85;

        const block = g.append("g")
          .attr("class", "minute-block")
          .on("mouseenter", function (event) {
            showTooltip(event, player, min);
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
          .attr("fill", teamColor)
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

      // Minutes label (left)
      svg.append("text")
        .attr("x", MINUTES_LABEL_WIDTH - 8)
        .attr("y", rowCenterY)
        .attr("text-anchor", "end")
        .attr("dominant-baseline", "central")
        .attr("fill", "#888")
        .attr("font-size", "11px")
        .text(formatMMSS(player.totalSeconds));

      // Player name (right of chart)
      svg.append("text")
        .attr("x", rightStart)
        .attr("y", rowCenterY)
        .attr("text-anchor", "start")
        .attr("dominant-baseline", "central")
        .attr("fill", "#ccc")
        .attr("font-size", "12px")
        .attr("font-weight", player.isStarter ? "bold" : "normal")
        .text(player.name);

      // Box score values
      const gs = player.gameStats || {};
      const pm = player.totalPlusMinus || 0;

      BOX_COLS.forEach((col, ci) => {
        let val;
        if (col.key === "pm") {
          val = pm > 0 ? `+${pm}` : `${pm}`;
        } else {
          val = col.fmt(gs);
        }
        const fillColor = col.key === "pm"
          ? (pm > 0 ? PM_POSITIVE_COLOR : pm < 0 ? "#ef5350" : "#888")
          : "#999";

        svg.append("text")
          .attr("x", tableStart + ci * STAT_COL_W + STAT_COL_W / 2)
          .attr("y", rowCenterY)
          .attr("text-anchor", "middle")
          .attr("dominant-baseline", "central")
          .attr("fill", fillColor)
          .attr("font-size", STAT_FONT)
          .text(val);
      });
    });

    // +/- row at bottom
    const pmY = numPlayers * CELL_STEP_Y + STARTER_SEPARATOR + 6;
    teamPM.forEach((pm, minute) => {
      if (pm === 0) return;
      const x = minuteToX(minute, periods);
      const color = pm > 0 ? PM_POSITIVE_COLOR : PM_NEGATIVE_COLOR;
      const absPm = Math.abs(pm);
      const maxPm = Math.max(...teamPM.map(Math.abs), 1);
      const barHeight = (absPm / maxPm) * CELL_H;

      g.append("rect")
        .attr("x", x)
        .attr("y", pmY + (CELL_H - barHeight))
        .attr("width", CELL_W)
        .attr("height", barHeight)
        .attr("rx", 1)
        .attr("fill", color)
        .attr("opacity", 0.8);

      if (absPm >= 3) {
        g.append("text")
          .attr("x", x + CELL_W / 2)
          .attr("y", pmY + CELL_H / 2)
          .attr("text-anchor", "middle")
          .attr("dominant-baseline", "central")
          .attr("fill", "#fff")
          .attr("font-size", "7px")
          .attr("font-weight", "bold")
          .text((pm > 0 ? "+" : "") + pm);
      }
    });

    // +/- label
    svg.append("text")
      .attr("x", rightStart)
      .attr("y", HEADER_HEIGHT + pmY + CELL_H / 2)
      .attr("text-anchor", "start")
      .attr("dominant-baseline", "central")
      .attr("fill", "#888")
      .attr("font-size", "11px")
      .text("+/−");

    // Period labels at bottom
    const labelY = pmY + CELL_H + 15;
    periods.forEach((p) => {
      const startX = minuteToX(p.startMinute, periods);
      const endX = minuteToX(p.endMinute - 1, periods) + CELL_W;
      const centerX = (startX + endX) / 2;

      g.append("text")
        .attr("x", centerX)
        .attr("y", labelY)
        .attr("text-anchor", "middle")
        .attr("fill", "#666")
        .attr("font-size", "11px")
        .text(p.label);
    });
  }

  // Tooltip
  const tooltip = d3.select("#tooltip");

  function showTooltip(event, player, minuteData) {
    const minute = minuteData.minute;
    const s = minuteData.stats || {};

    const pm = minuteData.plusMinus;
    const pmClass = pm > 0 ? "positive" : pm < 0 ? "negative" : "";
    const pmStr = pm > 0 ? `+${pm}` : `${pm}`;

    const pct = Math.round((minuteData.onCourtSeconds / 60) * 100);
    const coverageStr = pct >= 100
      ? "celá minuta"
      : `${minuteData.onCourtSeconds}s z 60s (${pct}%)`;

    let html = `<div class="player-name">${player.name} (#${player.shirtNumber})</div>`;
    html += `<div class="detail">Minuta: ${minute + 1} · Na hřišti: ${coverageStr}</div>`;
    html += `<div class="detail ${pmClass}">+/−: ${pmStr}</div>`;

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

  // Load data and render
  function init() {
    const dataUrl = `../data/${GAME_ID}.json`;
    d3.json(dataUrl).then((data) => {
      renderTeamChart("#chart-team1", data, "1");
      renderTeamChart("#chart-team2", data, "2");
    });
  }

  init();
})();
