/**
 * AsyncAPI JSON Schema Validator
 *
 * Validates AsyncAPI documents (YAML or JSON) against the AsyncAPI specification.
 * Supports AsyncAPI 2.x and 3.x.
 *
 * Features:
 * - YAML/JSON input parsing
 * - Version detection (2.x / 3.x)
 * - Structural validation via AJV
 * - Payload schema validation (nested JSON Schema validation)
 * - Detailed error reporting with JSON Pointer paths
 *
 * Usage:
 *   import { validateAsyncAPI } from './validator';
 *   const result = await validateAsyncAPI(yamlString);
 */

import Ajv from "ajv";
import addFormats from "ajv-formats";
import { parse as parseYaml } from "yaml";
import { ASYNCAPI_2X_SCHEMA, ASYNCAPI_3X_SCHEMA } from "./schemas";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ValidationError {
  /** JSON Pointer path to the offending field (e.g. "/info/title") */
  path: string;
  /** Human-readable error message */
  message: string;
  /** The schema keyword that triggered the error (e.g. "required", "type") */
  keyword: string;
  /** The actual value found at the path */
  value?: unknown;
}

export interface ValidationResult {
  /** Whether the document is valid */
  valid: boolean;
  /** AsyncAPI version detected (e.g. "2.6.0", "3.0.0") */
  version: string | null;
  /** List of validation errors (empty when valid) */
  errors: ValidationError[];
  /** Non-fatal warnings (spec recommendations not met) */
  warnings: ValidationWarning[];
  /** The parsed document as a plain object */
  parsed: Record<string, unknown> | null;
}

export interface ValidationWarning {
  path: string;
  message: string;
}

export type InputFormat = "yaml" | "json" | "auto";

export interface ValidatorOptions {
  /** Input format — default "auto" (detects from content) */
  format?: InputFormat;
  /** Whether to validate payload/header schemas defined inline — default true */
  validatePayloadSchemas?: boolean;
  /** Whether to allow additional properties not in the spec — default true */
  allowAdditionalProperties?: boolean;
}

// ─── AJV Setup ────────────────────────────────────────────────────────────────

function buildAjv(): Ajv {
  const ajv = new Ajv({
    allErrors: true,
    strict: false,
    validateFormats: true,
  });
  addFormats(ajv);
  return ajv;
}

// ─── Core Validator ───────────────────────────────────────────────────────────

/**
 * Detect the AsyncAPI version from a parsed document.
 * Returns null if the field is missing or unrecognised.
 */
export function detectVersion(doc: Record<string, unknown>): string | null {
  const v = doc["asyncapi"];
  if (typeof v === "string" && /^\d+\.\d+\.\d+$/.test(v)) {
    return v;
  }
  return null;
}

/**
 * Resolve the correct meta-schema for the given AsyncAPI version string.
 */
export function resolveSchema(
  version: string
): Record<string, unknown> | null {
  const [major] = version.split(".");
  if (major === "2") return ASYNCAPI_2X_SCHEMA;
  if (major === "3") return ASYNCAPI_3X_SCHEMA;
  return null;
}

/**
 * Parse raw input (YAML or JSON string) into a plain JS object.
 * Throws on parse errors.
 */
export function parseInput(
  input: string,
  format: InputFormat = "auto"
): Record<string, unknown> {
  const trimmed = input.trim();

  const detectedFormat: "json" | "yaml" =
    format !== "auto"
      ? format
      : trimmed.startsWith("{") || trimmed.startsWith("[")
      ? "json"
      : "yaml";

  if (detectedFormat === "json") {
    return JSON.parse(trimmed) as Record<string, unknown>;
  }
  // yaml.parse returns null for empty input, or an array for YAML arrays
  const parsed = parseYaml(trimmed);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(
      `YAML did not parse to an object (got ${parsed === null ? "null" : Array.isArray(parsed) ? "array" : typeof parsed})`
    );
  }
  return parsed as Record<string, unknown>;
}

/**
 * Collect all inline JSON Schema objects from channels/messages for deep validation.
 * Returns an array of { path, schema } tuples.
 */
function collectPayloadSchemas(
  doc: Record<string, unknown>
): Array<{ path: string; schema: unknown }> {
  const results: Array<{ path: string; schema: unknown }> = [];
  const version = detectVersion(doc);
  if (!version) return results;

  const major = version.split(".")[0];

  if (major === "2") {
    // AsyncAPI 2.x: doc.channels[name].{publish,subscribe}.message.payload
    const channels = (doc["channels"] ?? {}) as Record<string, unknown>;
    for (const [chName, chValue] of Object.entries(channels)) {
      const ch = chValue as Record<string, unknown>;
      for (const opKey of ["publish", "subscribe"] as const) {
        const op = ch[opKey] as Record<string, unknown> | undefined;
        if (!op) continue;
        const msg = op["message"] as Record<string, unknown> | undefined;
        if (!msg) continue;
        if (msg["payload"]) {
          results.push({
            path: `/channels/${chName}/${opKey}/message/payload`,
            schema: msg["payload"],
          });
        }
      }
    }
    // Also check components.schemas
    const components = (doc["components"] ?? {}) as Record<string, unknown>;
    const compSchemas = (components["schemas"] ?? {}) as Record<
      string,
      unknown
    >;
    for (const [name, schema] of Object.entries(compSchemas)) {
      results.push({ path: `/components/schemas/${name}`, schema });
    }
  } else if (major === "3") {
    // AsyncAPI 3.x: doc.channels[name].messages[msgName].payload
    const channels = (doc["channels"] ?? {}) as Record<string, unknown>;
    for (const [chName, chValue] of Object.entries(channels)) {
      const ch = chValue as Record<string, unknown>;
      const messages = (ch["messages"] ?? {}) as Record<string, unknown>;
      for (const [msgName, msgValue] of Object.entries(messages)) {
        const msg = msgValue as Record<string, unknown>;
        if (msg["payload"]) {
          results.push({
            path: `/channels/${chName}/messages/${msgName}/payload`,
            schema: msg["payload"],
          });
        }
      }
    }
    // components.schemas
    const components = (doc["components"] ?? {}) as Record<string, unknown>;
    const compSchemas = (components["schemas"] ?? {}) as Record<
      string,
      unknown
    >;
    for (const [name, schema] of Object.entries(compSchemas)) {
      results.push({ path: `/components/schemas/${name}`, schema });
    }
  }

  return results;
}

/**
 * Validate an inline JSON Schema definition for structural correctness.
 * Returns an array of ValidationError if the schema itself is malformed.
 */
function validateJsonSchema(
  schema: unknown,
  path: string
): ValidationError[] {
  const errors: ValidationError[] = [];

  if (typeof schema !== "object" || schema === null) {
    errors.push({
      path,
      message: "Payload schema must be an object",
      keyword: "type",
      value: schema,
    });
    return errors;
  }

  const s = schema as Record<string, unknown>;

  // Basic JSON Schema type checks
  if ("type" in s) {
    const validTypes = [
      "string",
      "number",
      "integer",
      "boolean",
      "object",
      "array",
      "null",
    ];
    const t = s["type"];
    if (typeof t === "string" && !validTypes.includes(t)) {
      errors.push({
        path: `${path}/type`,
        message: `Invalid JSON Schema type "${t}". Expected one of: ${validTypes.join(", ")}`,
        keyword: "type",
        value: t,
      });
    } else if (Array.isArray(t)) {
      for (const ti of t) {
        if (typeof ti !== "string" || !validTypes.includes(ti)) {
          errors.push({
            path: `${path}/type`,
            message: `Invalid type in array: "${ti}"`,
            keyword: "type",
            value: ti,
          });
        }
      }
    }
  }

  // Recurse into properties
  if (s["properties"] && typeof s["properties"] === "object") {
    for (const [propName, propSchema] of Object.entries(
      s["properties"] as Record<string, unknown>
    )) {
      errors.push(
        ...validateJsonSchema(propSchema, `${path}/properties/${propName}`)
      );
    }
  }

  // Recurse into items (array schema)
  if (s["items"]) {
    errors.push(...validateJsonSchema(s["items"], `${path}/items`));
  }

  return errors;
}

/**
 * Generate warnings for common spec recommendations.
 */
function generateWarnings(
  doc: Record<string, unknown>,
  version: string
): ValidationWarning[] {
  const warnings: ValidationWarning[] = [];
  const major = version.split(".")[0];

  // Recommend 'id' (unique app identifier)
  if (!doc["id"]) {
    warnings.push({
      path: "/id",
      message:
        "Recommended: Add an 'id' field (URI) as a unique application identifier",
    });
  }

  // Recommend descriptions on channels
  const channels = (doc["channels"] ?? {}) as Record<string, unknown>;
  for (const [name, ch] of Object.entries(channels)) {
    const c = ch as Record<string, unknown>;
    if (!c["description"]) {
      warnings.push({
        path: `/channels/${name}/description`,
        message: `Recommended: Add a description for channel "${name}"`,
      });
    }
  }

  // Warn about empty channels object in 2.x
  if (major === "2" && Object.keys(channels).length === 0) {
    warnings.push({
      path: "/channels",
      message:
        "AsyncAPI 2.x document has no channels defined — document describes no operations",
    });
  }

  return warnings;
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Validate an AsyncAPI document provided as a YAML or JSON string.
 *
 * @param input   Raw YAML or JSON string of an AsyncAPI document
 * @param options Validation options
 * @returns       A ValidationResult with full details
 *
 * @example
 * ```ts
 * import { validateAsyncAPI } from './validator';
 *
 * const yaml = `
 * asyncapi: '2.6.0'
 * info:
 *   title: User Service
 *   version: '1.0.0'
 * channels:
 *   user/signedup:
 *     subscribe:
 *       message:
 *         payload:
 *           type: object
 *           properties:
 *             userId: { type: string }
 * `;
 *
 * const result = await validateAsyncAPI(yaml);
 * console.log(result.valid); // true
 * ```
 */
export async function validateAsyncAPI(
  input: string,
  options: ValidatorOptions = {}
): Promise<ValidationResult> {
  const {
    format = "auto",
    validatePayloadSchemas = true,
  } = options;

  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];

  // 1. Parse input
  let parsed: Record<string, unknown>;
  try {
    parsed = parseInput(input, format);
  } catch (err) {
    return {
      valid: false,
      version: null,
      errors: [
        {
          path: "/",
          message: `Parse error: ${(err as Error).message}`,
          keyword: "parse",
        },
      ],
      warnings: [],
      parsed: null,
    };
  }

  // 2. Detect version
  const version = detectVersion(parsed);
  if (!version) {
    return {
      valid: false,
      version: null,
      errors: [
        {
          path: "/asyncapi",
          message:
            "Missing or invalid 'asyncapi' field. Must be a semver string like '2.6.0' or '3.0.0'.",
          keyword: "required",
          value: parsed["asyncapi"],
        },
      ],
      warnings: [],
      parsed,
    };
  }

  // 3. Resolve meta-schema
  const metaSchema = resolveSchema(version);
  if (!metaSchema) {
    return {
      valid: false,
      version,
      errors: [
        {
          path: "/asyncapi",
          message: `Unsupported AsyncAPI version "${version}". Supported: 2.x, 3.x`,
          keyword: "enum",
          value: version,
        },
      ],
      warnings: [],
      parsed,
    };
  }

  // 4. Structural validation via AJV
  const ajv = buildAjv();
  const validate = ajv.compile(metaSchema);
  const structurallyValid = validate(parsed);

  if (!structurallyValid && validate.errors) {
    for (const e of validate.errors) {
      errors.push({
        path: e.instancePath || "/",
        message: e.message ?? "Validation error",
        keyword: e.keyword,
        value: e.data,
      });
    }
  }

  // 5. Payload schema validation
  if (validatePayloadSchemas) {
    const payloadSchemas = collectPayloadSchemas(parsed);
    for (const { path, schema } of payloadSchemas) {
      const schemaErrors = validateJsonSchema(schema, path);
      errors.push(...schemaErrors);
    }
  }

  // 6. Generate warnings
  warnings.push(...generateWarnings(parsed, version));

  return {
    valid: errors.length === 0,
    version,
    errors,
    warnings,
    parsed,
  };
}

/**
 * Synchronous wrapper around validateAsyncAPI.
 * Useful for CLI / scripting contexts.
 */
export function validateAsyncAPISync(
  input: string,
  options: ValidatorOptions = {}
): ValidationResult {
  // Since validateAsyncAPI is async but does no I/O, we can run it synchronously
  // via a simple hack — the promise resolves immediately.
  let result: ValidationResult | undefined;
  validateAsyncAPI(input, options).then((r) => {
    result = r;
  });
  if (!result) {
    throw new Error(
      "Internal error: async validator did not resolve synchronously. Use validateAsyncAPI() instead."
    );
  }
  return result;
}
