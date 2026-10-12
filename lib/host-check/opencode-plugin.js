// OpenCode plugin: run shell commands past the host-check guard.
// bin/sync links this to ~/.config/opencode/plugins/host-check.js.
// V2 calls setup() and names the tool "shell"; V1 (1.18.29+) calls server() and names it "bash".
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const GUARD = join(homedir(), ".local/lib/host-check/guard.py");

function guard(command) {
  if (typeof command !== "string") return;
  const result = spawnSync("/usr/bin/python3", [GUARD, "opencode"], {
    input: JSON.stringify({ command }),
    encoding: "utf8",
    timeout: 5000,
  });
  if (result.error || result.status !== 0) {
    throw new Error(result.stderr?.trim() || `Host validation guard failed; inspect ${GUARD}.`);
  }
}

export default {
  id: "fleet.host-check",
  async setup(ctx) {
    await ctx.tool.hook("execute.before", (event) => {
      if (event.tool === "shell") guard(event.input?.command);
    });
  },
  server: async () => ({
    "tool.execute.before": async (input, output) => {
      if (input.tool === "bash") guard(output.args.command);
    },
  }),
};
