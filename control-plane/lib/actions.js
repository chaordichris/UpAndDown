// Whitelisted action runner. The config file is the security boundary:
// fixed argv per action, spawned without a shell, no user-supplied arguments.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";

const MAX_RUNS_KEPT = 50;
const MAX_OUTPUT_CHARS = 200_000;
const RUN_TIMEOUT_MS = 15 * 60 * 1000;

export class ActionRunner {
  constructor(root, actions) {
    this.root = root;
    this.actions = new Map(actions.map((a) => [a.id, a]));
    this.runs = new Map();
  }

  start(actionId) {
    const action = this.actions.get(actionId);
    if (!action) return { error: `action '${actionId}' is not whitelisted` };
    const running = [...this.runs.values()].find((r) => r.action_id === actionId && r.status === "running");
    if (running) return { error: `action '${actionId}' is already running`, run_id: running.id };

    const id = randomUUID().slice(0, 8);
    const run = {
      id,
      action_id: actionId,
      label: action.label,
      status: "running",
      started_at: new Date().toISOString(),
      finished_at: null,
      exit_code: null,
      output: "",
    };
    this.runs.set(id, run);
    this.#trim();

    const child = spawn(action.argv[0], action.argv.slice(1), {
      cwd: path.resolve(this.root, action.cwd ?? "."),
      shell: false,
      env: process.env,
    });
    const append = (chunk) => {
      run.output = (run.output + chunk.toString()).slice(-MAX_OUTPUT_CHARS);
    };
    child.stdout.on("data", append);
    child.stderr.on("data", append);

    const timer = setTimeout(() => {
      append(`\n[control-plane] timeout after ${RUN_TIMEOUT_MS / 1000}s, killing\n`);
      child.kill("SIGKILL");
    }, RUN_TIMEOUT_MS);

    child.on("error", (err) => {
      clearTimeout(timer);
      run.status = "error";
      run.finished_at = new Date().toISOString();
      append(`\n[control-plane] spawn error: ${err.message}\n`);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (run.status === "running") run.status = code === 0 ? "ok" : "failed";
      run.exit_code = code;
      run.finished_at = new Date().toISOString();
    });

    return { run_id: id, action_id: actionId, status: "running" };
  }

  get(id) {
    return this.runs.get(id) ?? null;
  }

  list() {
    return [...this.runs.values()]
      .sort((a, b) => b.started_at.localeCompare(a.started_at))
      .map(({ output, ...meta }) => meta);
  }

  #trim() {
    const ids = [...this.runs.keys()];
    while (ids.length > MAX_RUNS_KEPT) this.runs.delete(ids.shift());
  }
}
