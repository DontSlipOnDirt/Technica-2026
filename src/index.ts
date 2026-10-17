import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { NessieApiError, NessieClient } from "./nessie.js";

const apiKey = process.env.NESSIE_API_KEY;
if (!apiKey) {
  throw new Error("NESSIE_API_KEY is required");
}

const maxResultItems = Number(process.env.MCP_MAX_RESULT_ITEMS ?? "25");
const client = new NessieClient({
  apiKey,
  baseUrl: process.env.NESSIE_BASE_URL,
});
const completedTransferKeys = new Set<string>();

const server = new McpServer({
  name: "nessie-banking",
  version: "0.1.0",
});

function result(data: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data) }],
  };
}

function errorResult(error: unknown) {
  const message = error instanceof NessieApiError ? error.message : "Nessie request failed";
  return {
    isError: true,
    content: [{ type: "text" as const, text: message }],
  };
}

function boundedList(data: unknown) {
  return Array.isArray(data) ? data.slice(0, maxResultItems) : data;
}

function resourceId(id: string) {
  return encodeURIComponent(id);
}

server.tool(
  "list_customers",
  "List Nessie customers. Use filters when the user provides a name.",
  {
    firstName: z.string().optional().describe("Optional first-name filter"),
    lastName: z.string().optional().describe("Optional last-name filter"),
  },
  async ({ firstName, lastName }) => {
    try {
      const params = new URLSearchParams();
      if (firstName) params.set("firstName", firstName);
      if (lastName) params.set("lastName", lastName);
      const suffix = params.size ? `?${params.toString()}` : "";
      return result(boundedList(await client.get(`/customers${suffix}`)));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "get_customer",
  "Get a Nessie customer profile by ID.",
  { customerId: z.string().min(1).describe("Nessie customer ID") },
  async ({ customerId }) => {
    try {
      return result(await client.get(`/customers/${resourceId(customerId)}`));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "get_customer_accounts",
  "List the bank accounts belonging to a Nessie customer.",
  { customerId: z.string().min(1).describe("Nessie customer ID") },
  async ({ customerId }) => {
    try {
      const accounts = await client.get<unknown[]>(`/customers/${resourceId(customerId)}/accounts`);
      return result(boundedList(accounts));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "get_account",
  "Get details and balance information for one Nessie account.",
  { accountId: z.string().min(1).describe("Nessie account ID") },
  async ({ accountId }) => {
    try {
      return result(await client.get(`/accounts/${resourceId(accountId)}`));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "list_account_activity",
  "List recent purchases, transfers, deposits, withdrawals, or bills for a Nessie account.",
  {
    accountId: z.string().min(1).describe("Nessie account ID"),
    activityType: z.enum(["purchases", "transfers", "deposits", "withdrawals", "bills"]).default("purchases"),
  },
  async ({ accountId, activityType }) => {
    try {
      const activity = await client.get<unknown[]>(
        `/accounts/${resourceId(accountId)}/${activityType}`,
      );
      return result(boundedList(activity));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "find_merchants",
  "Find merchants in the Nessie merchant directory by name or category.",
  {
    name: z.string().optional().describe("Optional merchant name filter"),
    category: z.string().optional().describe("Optional merchant category filter"),
  },
  async ({ name, category }) => {
    try {
      const params = new URLSearchParams();
      if (name) params.set("name", name);
      if (category) params.set("category", category);
      const suffix = params.size ? `?${params.toString()}` : "";
      const merchants = await client.get<unknown[]>(`/merchants${suffix}`);
      return result(boundedList(merchants));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "get_merchant",
  "Get a Nessie merchant profile by ID.",
  { merchantId: z.string().min(1).describe("Nessie merchant ID") },
  async ({ merchantId }) => {
    try {
      return result(await client.get(`/merchants/${resourceId(merchantId)}`));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "list_atms",
  "List Nessie ATM locations, optionally filtered by latitude and longitude.",
  {
    latitude: z.number().finite().optional(),
    longitude: z.number().finite().optional(),
  },
  async ({ latitude, longitude }) => {
    try {
      const params = new URLSearchParams();
      if (latitude !== undefined) params.set("latitude", String(latitude));
      if (longitude !== undefined) params.set("longitude", String(longitude));
      const suffix = params.size ? `?${params.toString()}` : "";
      return result(boundedList(await client.get(`/atms${suffix}`)));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "list_branches",
  "List Nessie bank branch locations, optionally filtered by latitude and longitude.",
  {
    latitude: z.number().finite().optional(),
    longitude: z.number().finite().optional(),
  },
  async ({ latitude, longitude }) => {
    try {
      const params = new URLSearchParams();
      if (latitude !== undefined) params.set("latitude", String(latitude));
      if (longitude !== undefined) params.set("longitude", String(longitude));
      const suffix = params.size ? `?${params.toString()}` : "";
      return result(boundedList(await client.get(`/branches${suffix}`)));
    } catch (error) {
      return errorResult(error);
    }
  },
);

server.tool(
  "create_transfer",
  "Create a transfer from a Nessie account. Only call after the user has explicitly confirmed the exact amount and payee.",
  {
    accountId: z.string().min(1).describe("Source Nessie account ID"),
    payeeId: z.string().min(1).describe("Destination Nessie customer or account ID, as required by the configured Nessie dataset"),
    amount: z.number().positive().finite().describe("Transfer amount in dollars"),
    description: z.string().max(140).optional().describe("Short transfer description"),
    confirmed: z.literal(true).describe("Must be true only after the user confirms the exact amount and payee"),
    idempotencyKey: z.string().min(8).max(128).describe("Unique key for this confirmed transfer attempt"),
  },
  async ({ accountId, payeeId, amount, description, confirmed, idempotencyKey }) => {
    try {
      if (!confirmed) {
        return errorResult(new Error("Transfer requires explicit confirmation"));
      }
      if (completedTransferKeys.has(idempotencyKey)) {
        return errorResult(new Error("This transfer idempotency key was already used"));
      }

      const transfer = await client.post(
        `/accounts/${resourceId(accountId)}/transfers`,
        {
          medium: "balance",
          payee_id: payeeId,
          amount,
          ...(description ? { description } : {}),
        },
      );
      completedTransferKeys.add(idempotencyKey);
      return result(transfer);
    } catch (error) {
      return errorResult(error);
    }
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);