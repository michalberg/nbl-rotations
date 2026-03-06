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

  function slugify(text) {
    return text
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "");
  }

  function dateToSeason(dateStr) {
    if (!dateStr) return "unknown";
    const parts = dateStr.split("-");
    const year = parseInt(parts[0]);
    const month = parseInt(parts[1]);
    const startYear = month >= 9 ? year : year - 1;
    const endYear = startYear + 1;
    return `${startYear}-${String(endYear).slice(-2)}`;
  }

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
    const season = dateToSeason(data.date || "");
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
      20; // period labels

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
        .text(player.isDNP || player.totalSeconds === 0 ? "DNP" : formatMMSS(player.totalSeconds));

      // Player name (right of chart) — link to player page
      const playerLink = svg.append("a");
      if (player.firstName && player.familyName && season !== "unknown") {
        const playerSlug = `${slugify(teamInfo.name)}-${slugify(player.firstName)}-${slugify(player.familyName)}`;
        playerLink.attr("href", `../player/${season}/${playerSlug}.html`);
      }
      playerLink.append("text")
        .attr("x", rightStart)
        .attr("y", rowCenterY)
        .attr("text-anchor", "start")
        .attr("dominant-baseline", "central")
        .attr("fill", player.firstName ? "#6a9fd8" : "#ccc")
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

    // Period labels at bottom
    const labelY = numPlayers * CELL_STEP_Y + STARTER_SEPARATOR + 12;
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

  // ── Scoring development chart ───────────────────────────────────────────────
  function renderScoringChart(data) {
    const container = d3.select("#chart-scoring");
    if (!container.node()) return;
    const timeline = data.scoreTimeline;
    if (!timeline || timeline.length < 2) return;

    const periods = data.periods;
    const mL = 36, mT = 28, mB = 24, mR = 16;
    const containerW = Math.max(300, container.node().getBoundingClientRect().width || 400);
    const plotW = containerW - mL - mR;
    const plotH = 120;
    const svgW = containerW;
    const svgH = mT + plotH + mB;

    const totalSec = data.totalMinutes * 60;
    const xScale = d3.scaleLinear().domain([0, totalSec]).range([0, plotW]);

    const diffs = timeline.map(d => d.s1 - d.s2);
    const maxAbs = Math.max(Math.abs(d3.min(diffs)), Math.abs(d3.max(diffs)), 5);
    const yScale = d3.scaleLinear().domain([-maxAbs, maxAbs]).range([plotH, 0]);
    const y0 = yScale(0); // plotH/2 since domain is symmetric

    const c1 = TEAM_COLORS["1"], c2 = TEAM_COLORS["2"];

    container.append("div").attr("class", "team-header")
      .style("display", "flex").style("justify-content", "space-between").style("align-items", "center")
      .html(`<span>Vývoj skóre</span>
        <span style="display:flex;gap:16px;font-size:11px;color:#aaa">
          <span><span style="display:inline-block;width:12px;height:3px;background:${c1};margin-right:4px;vertical-align:middle;border-radius:1px"></span>${data.team1.name}</span>
          <span><span style="display:inline-block;width:12px;height:3px;background:${c2};margin-right:4px;vertical-align:middle;border-radius:1px"></span>${data.team2.name}</span>
        </span>`);

    const svg = container.append("svg")
      .attr("width", svgW).attr("height", svgH);

    const g = svg.append("g").attr("transform", `translate(${mL},${mT})`);

    // Plot background so tied-score gaps show page color rather than SVG default
    g.append("rect")
      .attr("x", 0).attr("y", 0).attr("width", plotW).attr("height", plotH)
      .attr("fill", "#16213e");

    // Y-axis grid + tick labels
    yScale.ticks(6).forEach(t => {
      g.append("line")
        .attr("x1", 0).attr("x2", plotW).attr("y1", yScale(t)).attr("y2", yScale(t))
        .attr("stroke", t === 0 ? "#555" : "#1e2040").attr("stroke-width", t === 0 ? 1 : 0.5);
      g.append("text")
        .attr("x", -5).attr("y", yScale(t) + 4).attr("text-anchor", "end")
        .attr("fill", "#555").attr("font-size", "9px")
        .text(t > 0 ? `+${t}` : t === 0 ? "0" : t);
    });

    const last = timeline[timeline.length - 1];
    const pts = [...timeline, { t: totalSec, s1: last.s1, s2: last.s2 }];

    // Team1 area: above zero (Math.max ensures no overlap with team2 area)
    g.append("path").datum(pts)
      .attr("fill", c1).attr("fill-opacity", 0.9)
      .attr("d", d3.area()
        .x(d => xScale(d.t)).y0(y0)
        .y1(d => yScale(Math.max(0, d.s1 - d.s2)))
        .curve(d3.curveStepAfter));

    // Team2 area: below zero
    g.append("path").datum(pts)
      .attr("fill", c2).attr("fill-opacity", 0.9)
      .attr("d", d3.area()
        .x(d => xScale(d.t)).y0(y0)
        .y1(d => yScale(Math.min(0, d.s1 - d.s2)))
        .curve(d3.curveStepAfter));

    // Zero line
    g.append("line")
      .attr("x1", 0).attr("x2", plotW).attr("y1", y0).attr("y2", y0)
      .attr("stroke", "#555").attr("stroke-width", 1);

    // Period separators + labels
    periods.forEach((p, i) => {
      const startX = xScale(p.startMinute * 60);
      const midX = xScale((p.startMinute + p.endMinute) / 2 * 60);
      if (i > 0)
        g.append("line").attr("x1", startX).attr("x2", startX).attr("y1", 0).attr("y2", plotH)
          .attr("stroke", "#444").attr("stroke-width", 1).attr("stroke-dasharray", "3,2");
      g.append("text").attr("x", midX).attr("y", plotH + 16)
        .attr("text-anchor", "middle").attr("fill", "#666").attr("font-size", "10px").text(p.label);
    });
  }

  // ── Box score comparison ────────────────────────────────────────────────────
  function renderBoxScore(data) {
    const el = document.getElementById("chart-boxscore");
    if (!el) return;

    function sum(tno, key) {
      return data.players[tno].reduce((acc, p) => acc + (p.gameStats[key] || 0), 0);
    }
    function pct(m, a) { return a ? Math.round(m / a * 100) : 0; }

    const s = {
      "1": {
        pts: data.team1.score,
        fgm: sum("1","fgm"), fga: sum("1","fga"),
        fg2m: sum("1","fg2m"), fg2a: sum("1","fg2a"),
        fg3m: sum("1","fg3m"), fg3a: sum("1","fg3a"),
        ftm: sum("1","ftm"), fta: sum("1","fta"),
        reb: sum("1","reb"), oreb: sum("1","oreb"), dreb: sum("1","dreb"),
        ast: sum("1","ast"), stl: sum("1","stl"), blk: sum("1","blk"),
        tov: sum("1","tov"), pf: sum("1","pf"),
      },
      "2": {
        pts: data.team2.score,
        fgm: sum("2","fgm"), fga: sum("2","fga"),
        fg2m: sum("2","fg2m"), fg2a: sum("2","fg2a"),
        fg3m: sum("2","fg3m"), fg3a: sum("2","fg3a"),
        ftm: sum("2","ftm"), fta: sum("2","fta"),
        reb: sum("2","reb"), oreb: sum("2","oreb"), dreb: sum("2","dreb"),
        ast: sum("2","ast"), stl: sum("2","stl"), blk: sum("2","blk"),
        tov: sum("2","tov"), pf: sum("2","pf"),
      },
    };

    function pctRow(cat, m1, a1, m2, a2) {
      const p1 = pct(m1, a1), p2 = pct(m2, a2);
      return { cat,
        v1: `${p1}% <span style="font-weight:normal;font-size:0.72rem;color:#999">(${m1}/${a1})</span>`,
        v2: `${p2}% <span style="font-weight:normal;font-size:0.72rem;color:#999">(${m2}/${a2})</span>`,
        cmp1: p1, cmp2: p2, higherBetter: true };
    }

    const rows = [
      { cat: "Body",         v1: s["1"].pts, v2: s["2"].pts,
        cmp1: s["1"].pts, cmp2: s["2"].pts, higherBetter: true },
      pctRow("Střelba z pole", s["1"].fgm, s["1"].fga, s["2"].fgm, s["2"].fga),
      pctRow("Dvojky",         s["1"].fg2m, s["1"].fg2a, s["2"].fg2m, s["2"].fg2a),
      pctRow("Trojky",         s["1"].fg3m, s["1"].fg3a, s["2"].fg3m, s["2"].fg3a),
      pctRow("Trestné hody",   s["1"].ftm, s["1"].fta, s["2"].ftm, s["2"].fta),
      { cat: "Doskoky",      v1: `${s["1"].reb} <span style="font-weight:normal;font-size:0.72rem;color:#999">(${s["1"].oreb}+${s["1"].dreb})</span>`,
                             v2: `${s["2"].reb} <span style="font-weight:normal;font-size:0.72rem;color:#999">(${s["2"].oreb}+${s["2"].dreb})</span>`,
        cmp1: s["1"].reb, cmp2: s["2"].reb, higherBetter: true },
      { cat: "Asistence",    v1: s["1"].ast, v2: s["2"].ast, higherBetter: true },
      { cat: "Zisky",        v1: s["1"].stl, v2: s["2"].stl, higherBetter: true },
      { cat: "Bloky",        v1: s["1"].blk, v2: s["2"].blk, higherBetter: true },
      { cat: "Ztráty",       v1: s["1"].tov, v2: s["2"].tov, higherBetter: false },
      { cat: "Osobní chyby", v1: s["1"].pf,  v2: s["2"].pf,  higherBetter: false },
    ];

    const c1 = TEAM_COLORS["1"], c2 = TEAM_COLORS["2"];

    function splitBar(n1, n2, higherBetter) {
      const total = n1 + n2;
      if (!total) return '';
      const p1 = Math.round(n1 / total * 100);
      const better1 = higherBetter ? n1 > n2 : n1 < n2;
      return `<div style="display:flex;height:4px;border-radius:2px;overflow:hidden;margin-top:3px">
        <div style="width:${p1}%;background:${c1};opacity:${better1?0.9:0.35}"></div>
        <div style="width:${100-p1}%;background:${c2};opacity:${better1?0.35:0.9}"></div>
      </div>`;
    }

    const rowsHtml = rows.map(row => {
      const n1 = row.cmp1 !== undefined ? row.cmp1 : +row.v1;
      const n2 = row.cmp2 !== undefined ? row.cmp2 : +row.v2;
      return `<div style="display:grid;grid-template-columns:1fr 96px 1fr;align-items:center;
                  padding:5px 10px;border-bottom:1px solid #1e2040">
        <span style="color:#ccc;font-size:0.88rem;font-weight:bold;text-align:right;padding-right:10px">${row.v1}</span>
        <div>
          <div style="color:#666;font-size:0.65rem;text-align:center">${row.cat}</div>
          ${splitBar(n1, n2, row.higherBetter)}
        </div>
        <span style="color:#ccc;font-size:0.88rem;font-weight:bold;padding-left:10px">${row.v2}</span>
      </div>`;
    }).join("");

    el.innerHTML = `
      <div class="team-header" style="display:grid;grid-template-columns:1fr 96px 1fr;padding:0 10px 8px">
        <span style="color:#ddd;text-align:right;padding-right:10px">${data.team1.name}</span>
        <span></span>
        <span style="color:#ddd;padding-left:10px">${data.team2.name}</span>
      </div>
      ${rowsHtml}`;
  }

  function renderTeamStats(data) {
    const el = document.getElementById("chart-team-stats");
    if (!el) return;
    const tss = data.teamShotStats || {};
    function qs(tno, key) { return ((tss[tno] || {}).qualifiers || {})[key] || {}; }
    const t1 = tss["1"] || {}, t2 = tss["2"] || {};
    const c1 = TEAM_COLORS["1"], c2 = TEAM_COLORS["2"];

    function benchCell(benchPts, totalPts) {
      const pct = totalPts ? Math.round(benchPts / totalPts * 100) : 0;
      return `${benchPts} <span style="color:#666;font-size:0.75rem;font-weight:normal">(${pct}%)</span>`;
    }

    const cols = [
      { label: "Ze ztrát",    tip: "Body ze ztrát soupeře" },
      { label: "Paint",        tip: "Body z vymezeného území" },
      { label: "2. šance",    tip: "Body z druhých šancí (po útočném doskoky)" },
      { label: "Protiútoky",  tip: "Body z rychlých protiútoků" },
      { label: "Lavička",     tip: "Body z lavičky (% ze všech bodů týmu)" },
      { label: "Max. vedení", tip: "Největší vedení v zápase" },
      { label: "Scoring run", tip: "Nejdelší scoring run – po sobě jdoucí body bez odpovědi soupeře" },
    ];

    function val(tno, colIdx) {
      const t = tno === "1" ? t1 : t2;
      const score = tno === "1" ? data.team1.score : data.team2.score;
      switch(colIdx) {
        case 0: return qs(tno,"fromturnover").pts || 0;
        case 1: return qs(tno,"paint").pts || 0;
        case 2: return qs(tno,"secondchance").pts || 0;
        case 3: return qs(tno,"fastbreak").pts || 0;
        case 4: return benchCell(t.benchPts||0, score);
        case 5: return t.biggestLead || 0;
        case 6: return t.biggestRun || 0;
      }
    }
    function numVal(tno, colIdx) {
      const t = tno === "1" ? t1 : t2;
      const score = tno === "1" ? data.team1.score : data.team2.score;
      switch(colIdx) {
        case 0: return qs(tno,"fromturnover").pts || 0;
        case 1: return qs(tno,"paint").pts || 0;
        case 2: return qs(tno,"secondchance").pts || 0;
        case 3: return qs(tno,"fastbreak").pts || 0;
        case 4: return t.benchPts || 0;
        case 5: return t.biggestLead || 0;
        case 6: return t.biggestRun || 0;
      }
    }

    const thCells = cols.map(c =>
      `<th style="text-align:right;padding:7px 10px;background:#16213e;color:#666;font-size:0.68rem;
                  text-transform:uppercase;letter-spacing:0.5px;font-weight:normal;white-space:nowrap"
           title="${c.tip}">${c.label}</th>`
    ).join("");

    function teamRow(tno, name) {
      const tds = cols.map((_, i) =>
        `<td style="text-align:right;padding:7px 10px;font-weight:bold;color:#fff">${val(tno,i)}</td>`
      ).join("");
      return `<tr style="border-bottom:1px solid #222">
        <td style="padding:7px 10px;font-weight:bold;color:#fff;white-space:nowrap">${name}</td>
        ${tds}
      </tr>`;
    }

    el.innerHTML = `<div style="overflow-x:auto">
      <table style="border-collapse:collapse;width:100%;font-size:0.85rem;white-space:nowrap">
        <thead><tr>
          <th style="text-align:left;padding:7px 10px;background:#16213e;color:#555;font-size:0.68rem;
                     text-transform:uppercase;letter-spacing:0.5px;font-weight:normal">Tým</th>
          ${thCells}
        </tr></thead>
        <tbody>
          ${teamRow("1", data.team1.name)}
          ${teamRow("2", data.team2.name)}
        </tbody>
      </table>
    </div>`;
  }

  // Load data and render
  function init() {
    const dataUrl = `../data/${GAME_ID}.json`;
    d3.json(dataUrl).then((data) => {
      renderTeamChart("#chart-team1", data, "1");
      renderTeamChart("#chart-team2", data, "2");
      renderScoringChart(data);
      renderBoxScore(data);
      renderTeamStats(data);
    });
  }

  init();
})();
