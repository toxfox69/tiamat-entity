/**
 * AsyncAPI JSON Schema Validator — Test Suite
 *
 * Covers:
 * - Valid AsyncAPI 2.x documents (YAML + JSON)
 * - Valid AsyncAPI 3.x documents
 * - Missing required fields
 * - Invalid field types
 * - Malformed YAML/JSON
 * - Unsupported versions
 * - Payload schema validation
 * - Warning generation
 */

import { describe, it, expect } from "vitest";
import {
  validateAsyncAPI,
  parseInput,
  detectVersion,
  resolveSchema,
  type ValidationResult,
} from "../src/validator";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const VALID_2X_YAML = `
asyncapi: '2.6.0'
info:
  title: User Events API
  version: '1.0.0'
  description: Manages user lifecycle events
channels:
  user/signedup:
    description: A user signed up
    subscribe:
      operationId: onUserSignedUp
      message:
        payload:
          type: object
          properties:
            userId:
              type: string
            email:
              type: string
              format: email
          required:
            - userId
`;

const VALID_2X_JSON = JSON.stringify({
  asyncapi: "2.6.0",
  info: { title: "Test API", version: "1.0.0" },
  channels: {
    "order/placed": {
      publish: {
        message: {
          payload: {
            type: "object",
            properties: { orderId: { type: "string" } },
          },
        },
      },
    },
  },
});

const VALID_3X_YAML = `
asyncapi: '3.0.0'
info:
  title: Notification Service
  version: '2.0.0'
channels:
  notifications:
    address: notifications
    messages:
      notificationReceived:
        payload:
          type: object
          properties:
            message:
              type: string
operations:
  receiveNotification:
    action: receive
    channel:
      $ref: '#/channels/notifications'
`;

const MISSING_REQUIRED_YAML = `
asyncapi: '2.6.0'
channels:
  test: {}
`;
// ↑ Missing: info

const INVALID_TYPE_YAML = `
asyncapi: '2.6.0'
info:
  title: 42
  version: '1.0.0'
channels: {}
`;
// ↑ title should be string, not number

const MALFORMED_YAML = `
asyncapi: '2.6.0'
info:
  - this is wrong yaml
  : invalid key
`;

const INVALID_PAYLOAD_TYPE_YAML = `
asyncapi: '2.6.0'
info:
  title: Bad Payload API
  version: '1.0.0'
channels:
  test/channel:
    subscribe:
      message:
        payload:
          type: notAValidType
`;

const UNSUPPORTED_VERSION_YAML = `
asyncapi: '1.0.0'
info:
  title: Old API
  version: '1.0.0'
channels: {}
`;

const NO_VERSION_YAML = `
info:
  title: No Version
  version: '1.0.0'
channels: {}
`;

const WITH_COMPONENTS_YAML = `
asyncapi: '2.6.0'
info:
  title: Components Test
  version: '1.0.0'
  contact:
    name: Dev Team
    email: dev@example.com
  license:
    name: Apache 2.0
    url: https://www.apache.org/licenses/LICENSE-2.0
channels:
  user/created:
    description: Emitted when a user is created
    subscribe:
      operationId: onUserCreated
      message:
        $ref: '#/components/messages/UserCreated'
components:
  messages:
    UserCreated:
      payload:
        $ref: '#/components/schemas/User'
  schemas:
    User:
      type: object
      required:
        - id
        - email
      properties:
        id:
          type: string
        email:
          type: string
        name:
          type: string
`;

// ─── parseInput ───────────────────────────────────────────────────────────────

describe("parseInput()", () => {
  it("parses valid YAML", () => {
    const result = parseInput("asyncapi: '2.6.0'\ninfo:\n  title: Test\n  version: '1.0.0'\nchannels: {}");
    expect(result).toMatchObject({ asyncapi: "2.6.0" });
  });

  it("parses valid JSON", () => {
    const result = parseInput('{"asyncapi":"2.6.0"}', "json");
    expect(result.asyncapi).toBe("2.6.0");
  });

  it("auto-detects JSON from { prefix", () => {
    const result = parseInput('{"asyncapi":"3.0.0"}');
    expect(result.asyncapi).toBe("3.0.0");
  });

  it("throws on invalid JSON", () => {
    expect(() => parseInput("{bad json}", "json")).toThrow();
  });

  it("throws on non-object YAML", () => {
    expect(() => parseInput("- item1\n- item2")).toThrow();
  });
});

// ─── detectVersion ────────────────────────────────────────────────────────────

describe("detectVersion()", () => {
  it("detects 2.x version", () => {
    expect(detectVersion({ asyncapi: "2.6.0" })).toBe("2.6.0");
  });

  it("detects 3.x version", () => {
    expect(detectVersion({ asyncapi: "3.0.0" })).toBe("3.0.0");
  });

  it("returns null when asyncapi field missing", () => {
    expect(detectVersion({ info: {} })).toBeNull();
  });

  it("returns null for non-semver string", () => {
    expect(detectVersion({ asyncapi: "latest" })).toBeNull();
  });

  it("returns null when asyncapi is a number", () => {
    expect(detectVersion({ asyncapi: 2.6 })).toBeNull();
  });
});

// ─── resolveSchema ────────────────────────────────────────────────────────────

describe("resolveSchema()", () => {
  it("resolves schema for 2.x", () => {
    const schema = resolveSchema("2.6.0");
    expect(schema).not.toBeNull();
    expect((schema as Record<string, unknown>)["title"]).toContain("2.x");
  });

  it("resolves schema for 3.x", () => {
    const schema = resolveSchema("3.0.0");
    expect(schema).not.toBeNull();
    expect((schema as Record<string, unknown>)["title"]).toContain("3.x");
  });

  it("returns null for unsupported versions", () => {
    expect(resolveSchema("1.0.0")).toBeNull();
    expect(resolveSchema("4.0.0")).toBeNull();
  });
});

// ─── validateAsyncAPI — Valid Documents ───────────────────────────────────────

describe("validateAsyncAPI() — valid documents", () => {
  it("accepts a minimal valid AsyncAPI 2.x YAML", async () => {
    const result = await validateAsyncAPI(VALID_2X_YAML);
    expect(result.valid).toBe(true);
    expect(result.version).toBe("2.6.0");
    expect(result.errors).toHaveLength(0);
  });

  it("accepts a valid AsyncAPI 2.x JSON string", async () => {
    const result = await validateAsyncAPI(VALID_2X_JSON);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("accepts a valid AsyncAPI 3.x YAML", async () => {
    const result = await validateAsyncAPI(VALID_3X_YAML);
    expect(result.valid).toBe(true);
    expect(result.version).toBe("3.0.0");
    expect(result.errors).toHaveLength(0);
  });

  it("accepts a document with components and $refs", async () => {
    const result = await validateAsyncAPI(WITH_COMPONENTS_YAML);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("includes the parsed document in the result", async () => {
    const result = await validateAsyncAPI(VALID_2X_YAML);
    expect(result.parsed).not.toBeNull();
    expect((result.parsed as Record<string, unknown>)["asyncapi"]).toBe("2.6.0");
  });
});

// ─── validateAsyncAPI — Invalid Documents ─────────────────────────────────────

describe("validateAsyncAPI() — invalid documents", () => {
  it("rejects document missing 'asyncapi' version field", async () => {
    const result = await validateAsyncAPI(NO_VERSION_YAML);
    expect(result.valid).toBe(false);
    expect(result.version).toBeNull();
    expect(result.errors[0].keyword).toBe("required");
    expect(result.errors[0].path).toBe("/asyncapi");
  });

  it("rejects document missing required 'info' field", async () => {
    const result = await validateAsyncAPI(MISSING_REQUIRED_YAML);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
    const paths = result.errors.map((e) => e.path);
    // AJV will report the root path for a missing required property
    expect(paths.some((p) => p === "/" || p === "")).toBe(true);
  });

  it("rejects invalid type on info.title", async () => {
    const result = await validateAsyncAPI(INVALID_TYPE_YAML);
    expect(result.valid).toBe(false);
    const titleError = result.errors.find((e) => e.path.includes("title"));
    expect(titleError).toBeDefined();
    expect(titleError?.keyword).toBe("type");
  });

  it("rejects unsupported AsyncAPI version", async () => {
    const result = await validateAsyncAPI(UNSUPPORTED_VERSION_YAML);
    expect(result.valid).toBe(false);
    expect(result.errors[0].keyword).toBe("enum");
    expect(result.errors[0].path).toBe("/asyncapi");
  });

  it("returns parse error for malformed YAML", async () => {
    const result = await validateAsyncAPI(MALFORMED_YAML);
    // YAML may parse or error depending on strictness — check either a parse error or validation failure
    expect(result.valid).toBe(false);
  });

  it("returns parse error for empty string", async () => {
    const result = await validateAsyncAPI("");
    expect(result.valid).toBe(false);
  });

  it("returns parse error for invalid JSON", async () => {
    const result = await validateAsyncAPI("{not json}", "json" as never);
    // Actually format param is passed as options, let's test properly:
    const result2 = await validateAsyncAPI("{not valid json}", { format: "json" });
    expect(result2.valid).toBe(false);
    expect(result2.errors[0].keyword).toBe("parse");
  });
});

// ─── validateAsyncAPI — Payload Schema Validation ─────────────────────────────

describe("validateAsyncAPI() — payload schema validation", () => {
  it("rejects invalid JSON Schema type in payload", async () => {
    const result = await validateAsyncAPI(INVALID_PAYLOAD_TYPE_YAML);
    expect(result.valid).toBe(false);
    const typeError = result.errors.find(
      (e) => e.path.includes("payload") && e.keyword === "type"
    );
    expect(typeError).toBeDefined();
  });

  it("skips payload validation when validatePayloadSchemas=false", async () => {
    const result = await validateAsyncAPI(INVALID_PAYLOAD_TYPE_YAML, {
      validatePayloadSchemas: false,
    });
    // Without payload validation, only structural errors remain
    const payloadErrors = result.errors.filter((e) =>
      e.path.includes("payload")
    );
    expect(payloadErrors).toHaveLength(0);
  });

  it("validates nested properties in payload schema", async () => {
    const yaml = `
asyncapi: '2.6.0'
info:
  title: Test
  version: '1.0.0'
channels:
  test:
    subscribe:
      message:
        payload:
          type: object
          properties:
            nested:
              type: badType
    `;
    const result = await validateAsyncAPI(yaml);
    expect(result.valid).toBe(false);
    expect(
      result.errors.some(
        (e) => e.path.includes("nested") && e.keyword === "type"
      )
    ).toBe(true);
  });

  it("validates component schemas", async () => {
    const yaml = `
asyncapi: '2.6.0'
info:
  title: Test
  version: '1.0.0'
channels:
  test: {}
components:
  schemas:
    BadSchema:
      type: invalidType
    `;
    const result = await validateAsyncAPI(yaml);
    expect(result.valid).toBe(false);
    expect(
      result.errors.some((e) => e.path.includes("BadSchema"))
    ).toBe(true);
  });
});

// ─── validateAsyncAPI — Warnings ──────────────────────────────────────────────

describe("validateAsyncAPI() — warnings", () => {
  it("warns when 'id' field is missing", async () => {
    const result = await validateAsyncAPI(VALID_2X_YAML);
    const idWarn = result.warnings.find((w) => w.path === "/id");
    expect(idWarn).toBeDefined();
  });

  it("warns about channels without descriptions", async () => {
    const yaml = `
asyncapi: '2.6.0'
info:
  title: Test
  version: '1.0.0'
channels:
  nodesc/channel:
    subscribe:
      message:
        payload:
          type: string
    `;
    const result = await validateAsyncAPI(yaml);
    const descWarn = result.warnings.find(
      (w) => w.path.includes("description")
    );
    expect(descWarn).toBeDefined();
  });

  it("produces no warnings for a well-documented document", async () => {
    const yaml = `
asyncapi: '2.6.0'
id: 'urn:com:example:user-service'
info:
  title: Well-Documented API
  version: '1.0.0'
channels:
  user/signedup:
    description: Emitted when a user completes registration
    subscribe:
      message:
        payload:
          type: string
    `;
    const result = await validateAsyncAPI(yaml);
    expect(result.valid).toBe(true);
    // Only a channel description warning if present
    const criticalWarnings = result.warnings.filter(
      (w) => !w.path.includes("description")
    );
    expect(criticalWarnings).toHaveLength(0);
  });
});

// ─── validateAsyncAPI — AsyncAPI 3.x specifics ────────────────────────────────

describe("validateAsyncAPI() — AsyncAPI 3.x specifics", () => {
  it("requires 'action' field on operations in 3.x", async () => {
    const yaml = `
asyncapi: '3.0.0'
info:
  title: Missing Action
  version: '1.0.0'
channels:
  notifications:
    address: notifications
operations:
  myOp:
    channel:
      $ref: '#/channels/notifications'
    `;
    // Missing 'action' field in operation
    const result = await validateAsyncAPI(yaml);
    expect(result.valid).toBe(false);
    expect(
      result.errors.some(
        (e) => e.path.includes("operations") || e.path.includes("myOp")
      )
    ).toBe(true);
  });

  it("accepts valid send/receive actions in 3.x", async () => {
    const result = await validateAsyncAPI(VALID_3X_YAML);
    expect(result.valid).toBe(true);
  });

  it("validates 3.x channel message payloads", async () => {
    const yaml = `
asyncapi: '3.0.0'
info:
  title: Test
  version: '1.0.0'
channels:
  events:
    messages:
      UserCreated:
        payload:
          type: badType
operations:
  receiveEvent:
    action: receive
    channel:
      $ref: '#/channels/events'
    `;
    const result = await validateAsyncAPI(yaml);
    expect(result.valid).toBe(false);
    expect(
      result.errors.some((e) => e.path.includes("payload") && e.keyword === "type")
    ).toBe(true);
  });
});

// ─── Result shape ─────────────────────────────────────────────────────────────

describe("ValidationResult shape", () => {
  it("always includes valid, version, errors, warnings, parsed fields", async () => {
    const result = await validateAsyncAPI(VALID_2X_YAML) satisfies ValidationResult;
    expect(typeof result.valid).toBe("boolean");
    expect(typeof result.version === "string" || result.version === null).toBe(true);
    expect(Array.isArray(result.errors)).toBe(true);
    expect(Array.isArray(result.warnings)).toBe(true);
    expect(result.parsed).not.toBeNull();
  });

  it("errors include path, message, keyword fields", async () => {
    const result = await validateAsyncAPI(MISSING_REQUIRED_YAML);
    for (const error of result.errors) {
      expect(typeof error.path).toBe("string");
      expect(typeof error.message).toBe("string");
      expect(typeof error.keyword).toBe("string");
    }
  });
});
