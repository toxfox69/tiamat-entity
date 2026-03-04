#!/usr/bin/env node
/**
 * AsyncAPI JSON Schema Validator — CLI
 *
 * Usage:
 *   asyncapi-validator <file>           Validate a file
 *   asyncapi-validator --stdin          Read from stdin
 *   asyncapi-validator --help           Show help
 *
 * Exit codes:
 *   0  — valid
 *   1  — validation errors
 *   2  — parse/runtime error
 */

import { readFileSync } from "fs";
import { resolve } from "path";
import { validateAsyncAPI } from "./validator";

const HELP = `
asyncapi-validator — Validate AsyncAPI documents (YAML or JSON)

USAGE
  asyncapi-validator [options] <file>

OPTIONS
  --stdin           Read input from stdin instead of a file
  --no-payloads     Skip payload schema validation
  --json            Output result as JSON
  --quiet           Only output exit code (no text output)
  --help, -h        Show this help message

EXAMPLES
  asyncapi-validator spec.yaml
  asyncapi-validator spec.json --json
  cat spec.yaml | asyncapi-validator --stdin
  asyncapi-validator spec.yaml --no-payloads

EXIT CODES
  0  Valid document
  1  Validation errors found
  2  Parse / runtime error
`.trim();

async function main(): Promise<void> {
  const args = process.argv.slice(2);

  if (args.includes("--help") || args.includes("-h") || args.length === 0) {
    console.log(HELP);
    process.exit(0);
  }

  const useStdin = args.includes("--stdin");
  const jsonOutput = args.includes("--json");
  const quiet = args.includes("--quiet");
  const skipPayloads = args.includes("--no-payloads");

  const filePath = args.find(
    (a) => !a.startsWith("--") && a !== "--stdin"
  );

  let input: string;

  try {
    if (useStdin) {
      input = readFileSync("/dev/stdin", "utf-8");
    } else if (filePath) {
      input = readFileSync(resolve(filePath), "utf-8");
    } else {
      console.error("Error: provide a file path or use --stdin");
      process.exit(2);
    }
  } catch (err) {
    console.error(`Error reading input: ${(err as Error).message}`);
    process.exit(2);
  }

  const result = await validateAsyncAPI(input, {
    validatePayloadSchemas: !skipPayloads,
  });

  if (jsonOutput) {
    console.log(JSON.stringify(result, null, 2));
  } else if (!quiet) {
    const icon = result.valid ? "✓" : "✗";
    const status = result.valid ? "VALID" : "INVALID";
    console.log(`${icon} AsyncAPI ${result.version ?? "?"} — ${status}`);

    if (result.errors.length > 0) {
      console.log(`\nErrors (${result.errors.length}):`);
      for (const err of result.errors) {
        console.log(`  [${err.keyword}] ${err.path}  →  ${err.message}`);
      }
    }

    if (result.warnings.length > 0) {
      console.log(`\nWarnings (${result.warnings.length}):`);
      for (const warn of result.warnings) {
        console.log(`  ${warn.path}  →  ${warn.message}`);
      }
    }
  }

  process.exit(result.valid ? 0 : 1);
}

main().catch((err: Error) => {
  console.error("Fatal error:", err.message);
  process.exit(2);
});
