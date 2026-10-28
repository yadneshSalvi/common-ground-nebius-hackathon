import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const out = path.resolve("test-results/approval-regression");
await fs.mkdir(out, { recursive: true });
const report = {
  kind: "Narrow authored browser regression; real local owner API and signed consent; injected state/response changes; no root runtime or providers",
  started_at: new Date().toISOString(),
  checks: [],
  network_blocked: [],
  errors: [],
};
const runtime = spawn(
  path.resolve(".venv/bin/python"),
  ["web/approval-qa-runtime.py"],
  { cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"] },
);
let startup = "",
  stderr = "",
  browser;
runtime.stderr.on("data", (chunk) => {
  stderr += chunk.toString();
});
try {
  const ready = await new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () =>
        reject(new Error("Disposable approval runtime did not become ready")),
      30000,
    );
    runtime.stdout.on("data", (chunk) => {
      startup += chunk.toString();
      const line = startup.split("\n").find((s) => s.startsWith('{"url"'));
      if (line) {
        clearTimeout(timeout);
        resolve(JSON.parse(line));
      }
    });
    runtime.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Disposable runtime exited ${code}: ${stderr}`));
    });
  });
  report.runtime = ready.url;
  const executablePath =
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
    path.join(
      os.homedir(),
      "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    );
  browser = await chromium.launch({ headless: true, executablePath });
  const context = await browser.newContext({
    viewport: { width: 1100, height: 1000 },
    reducedMotion: "reduce",
  });
  await context.route("**/*", (route) => {
    if (new URL(route.request().url()).origin !== ready.url) {
      report.network_blocked.push(route.request().url());
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => report.errors.push(error.message));
  await page.goto(`${ready.url}/#pair=${encodeURIComponent(ready.pair_code)}`);
  await expect(
    page.getByRole("heading", { name: "Your part in the next arrangement." }),
  ).toBeVisible({ timeout: 15000 });
  const notice = page.getByText(
    `Your approval is recorded for revision ${ready.revision}.`,
    { exact: true },
  );
  const checkbox = page.getByRole("checkbox", {
    name: /I reviewed this exact revision/,
  });
  async function approve() {
    await checkbox.check();
    const responsePromise = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url() === `${ready.url}/api/v2/approve`,
    );
    await page
      .getByRole("button", { name: "Approve my exact part", exact: true })
      .click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.consent?.signature).toBeTruthy();
    await expect(notice).toBeVisible();
    await expect(checkbox).toBeChecked();
    await expect(checkbox).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Approval recorded", exact: true }),
    ).toBeDisabled();
    return result;
  }
  const consent = await approve();
  report.checks.push({
    check:
      "Successful real signed owner consent shows exact-revision confirmation and disables repeat",
    passed: true,
    agreement_id: consent.consent.body.payload.agreement_id,
    revision: consent.consent.body.payload.revision,
  });
  await page
    .locator(".cg-owner-proposal")
    .screenshot({ path: path.join(out, "approval-recorded.png") });
  for (const field of [
    "agreement_id",
    "revision",
    "agreement_digest",
    "consent_revision",
    "constraint_revision",
  ]) {
    await page.reload();
    await expect(checkbox).toBeVisible();
    await approve();
    await page.route("**/api/v2/state", async (route) => {
      const response = await route.fetch();
      const state = await response.json();
      if (field === "agreement_id")
        state.pending.agreement_id = "authored-different-agreement";
      else if (field === "revision") state.pending.revision += 1;
      else if (field === "agreement_digest")
        state.pending_digest = "f".repeat(64);
      else state[field] += 1;
      await route.fulfill({ response, json: state });
    });
    await expect(notice).toHaveCount(0, { timeout: 10000 });
    await expect(checkbox).not.toBeChecked();
    await expect(
      page.getByRole("button", { name: "Approval recorded", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Approve my exact part", exact: true }),
    ).toBeDisabled();
    report.checks.push({
      check: `Injected current ${field} change clears confirmation and requires a new review`,
      passed: true,
    });
    await page.unroute("**/api/v2/state");
  }
  await page.reload();
  await expect(checkbox).toBeVisible();
  await page.route("**/api/v2/approve", async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    result.consent.body.payload.agreement_digest = "0".repeat(64);
    await route.fulfill({ response, json: result });
  });
  await checkbox.check();
  await page
    .getByRole("button", { name: "Approve my exact part", exact: true })
    .click();
  await expect(
    page.getByText(
      "The service returned no matching signed approval. Refresh your owner state before deciding again.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(notice).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Approval recorded", exact: true }),
  ).toHaveCount(0);
  await page
    .locator(".cg-owner-proposal")
    .screenshot({ path: path.join(out, "mismatching-response.png") });
  report.checks.push({
    check:
      "Injected successful HTTP response with mismatching consent digest cannot show approval success",
    passed: true,
  });
  report.runtime_observation = await (
    await fetch(`${ready.url}/__qa/report`)
  ).json();
  expect(report.runtime_observation.model_attempts).toBe(0);
  expect(report.runtime_observation.owner_signed_approval_present).toBe(true);
  expect(report.network_blocked).toEqual([]);
  report.status = "PASSED";
} catch (error) {
  report.status = "FAILED";
  report.errors.push(error.message);
  process.exitCode = 1;
} finally {
  await browser?.close();
  runtime.kill("SIGTERM");
  await new Promise((resolve) => {
    if (runtime.exitCode !== null) resolve();
    else {
      runtime.once("exit", resolve);
      setTimeout(() => {
        runtime.kill("SIGKILL");
        resolve();
      }, 5000).unref();
    }
  });
  report.finished_at = new Date().toISOString();
  await fs.writeFile(
    path.join(out, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
}
console.log(JSON.stringify(report, null, 2));
