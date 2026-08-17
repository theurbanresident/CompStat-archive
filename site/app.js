const state = { reports: [], filtered: [] };

const labels = {
  weekly_compstat: "Weekly CompStat",
  year_end_compstat: "Calendar year-end CompStat",
  wpd_year_end_report: "Narrative WPD year-end report",
};

function repositoryCoordinates() {
  const configured = document.querySelector('meta[name="github-repository"]')?.content;
  if (configured) return configured;
  if (!location.hostname.endsWith("github.io")) return "";
  const owner = location.hostname.split(".")[0];
  const repository = location.pathname.split("/").filter(Boolean)[0];
  return owner && repository ? `${owner}/${repository}` : "";
}

function repositoryBranch() {
  return document.querySelector('meta[name="github-default-branch"]')?.content || "main";
}

function text(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function releaseUrl(report) {
  if (report.release_url) return report.release_url;
  const repository = repositoryCoordinates();
  if (!repository) return "";
  return `https://github.com/${repository}/releases/download/${report.release_tag}/${report.release_asset}`;
}

function sourcePdfUrl(report) {
  const repository = repositoryCoordinates();
  if (repository && report.source_path) {
    const path = report.source_path.split("/").map(encodeURIComponent).join("/");
    return `https://raw.githubusercontent.com/${repository}/${repositoryBranch()}/${path}`;
  }
  return releaseUrl(report);
}

function period(report) {
  if (report.report_type === "weekly_compstat") {
    return `${report.report_start}<br><strong>to ${report.report_end}</strong>`;
  }
  return `<strong>${report.report_year}</strong>`;
}

function statusBadge(status) {
  const cls = status === "validated" ? "good" : status === "failed" ? "bad" : "warn";
  return `<span class="badge badge--${cls}">${text(status.replaceAll("_", " "))}</span>`;
}

function render() {
  const type = document.querySelector("#type-filter").value;
  const year = document.querySelector("#year-filter").value;
  const query = document.querySelector("#search-filter").value.toLowerCase().trim();
  state.filtered = state.reports.filter(report => {
    const haystack = `${report.report_id} ${report.title} ${report.report_end}`.toLowerCase();
    return (!type || report.report_type === type)
      && (!year || String(report.report_year) === year)
      && (!query || haystack.includes(query));
  });
  document.querySelector("#result-count").textContent = `${state.filtered.length} result${state.filtered.length === 1 ? "" : "s"}`;
  const rows = state.filtered.map(report => {
    const source = sourcePdfUrl(report);
    const files = [
      source ? `<a href="${text(source)}">Original PDF</a>` : "",
      report.data_path ? `<a href="${text(report.data_path)}">Extracted CSV</a>` : "",
      report.manifest_path ? `<a href="${text(report.manifest_path)}">Audit manifest</a>` : "",
      `<a href="${text(report.source_url)}">City source</a>`,
    ].filter(Boolean).join("");
    return `<tr>
      <td>${period(report)}</td>
      <td>${text(labels[report.report_type] || report.report_type)}<br><small>${text(report.report_id)}</small></td>
      <td>r${text(report.revision)}</td>
      <td>${statusBadge(report.validation_status)}${Number(report.validation_warning_count) ? `<br><small>${text(report.validation_warning_count)} source warning(s)</small>` : ""}</td>
      <td><span class="file-links">${files}</span></td>
      <td><span class="hash" title="${text(report.source_sha256)}">${text(report.source_sha256)}</span><small>SHA-256</small></td>
    </tr>`;
  }).join("");
  document.querySelector("#report-rows").innerHTML = rows || '<tr><td colspan="6">No reports match these filters.</td></tr>';
}

async function loadCatalog() {
  try {
    const response = await fetch("catalog/reports.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Catalog request returned ${response.status}`);
    state.reports = await response.json();
    const years = [...new Set(state.reports.map(report => report.report_year).filter(Boolean))].sort((a, b) => b - a);
    document.querySelector("#year-filter").insertAdjacentHTML("beforeend", years.map(year => `<option>${text(year)}</option>`).join(""));
    document.querySelector("#report-count").textContent = state.reports.length;
    document.querySelector("#weekly-count").textContent = state.reports.filter(report => report.report_type === "weekly_compstat").length;
    document.querySelector("#year-count").textContent = state.reports.filter(report => report.report_type !== "weekly_compstat").length;
    document.querySelector("#latest-date").textContent = state.reports[0]?.report_end || "-";
    render();
  } catch (error) {
    const target = document.querySelector("#load-error");
    target.hidden = false;
    target.textContent = `The archive catalog could not be loaded: ${error.message}`;
    document.querySelector("#report-rows").innerHTML = '<tr><td colspan="6">Catalog unavailable.</td></tr>';
  }
}

document.querySelector("#filters").addEventListener("input", render);
document.querySelector("#filters").addEventListener("reset", () => setTimeout(render));
loadCatalog();
