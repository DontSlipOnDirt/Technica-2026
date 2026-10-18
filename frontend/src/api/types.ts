// Shapes shared with the backend. Field names match the contract exactly (snake_case).

export type Decision = 'allow' | 'confirm' | 'hold'
// own_transfer: between the customer's own accounts. new_account: opening one (amount 0, needs a yes too).
export type Kind = 'transfer' | 'bill' | 'withdrawal' | 'deposit' | 'own_transfer' | 'loan' | 'new_account'
// unknown: the bank couldn't tell whether the money moved. It is never sent again.
export type TransferStatus = 'awaiting_yes' | 'held' | 'executed' | 'cancelled' | 'unknown'

/** The transfer the backend is currently working on, as GET /api/transfer/current returns it. */
export interface CurrentTransfer {
  transfer_id: string
  kind: Kind
  status: TransferStatus
  decision: Decision
  risk_score: number
  reasons: string[]
  spoken_message: string
  payee_name: string
  amount: number
  from_account_name: string
  /** new_account only: "Checking", "Savings", or "Credit Card". payee_name is the new account's nickname. */
  account_type?: string
  /** bill and loan only: what was owed before this payment, or null if the bank doesn't say. */
  amount_owed?: number | null
}

/** A backend error. The message is the backend's {"error": "..."} text. */
export class ApiError extends Error {}

/** What the app needs from the backend. The agent's tools live on the MCP server, not here. */
export interface BankApi {
  postTranscript(conversation_id: string, text: string): Promise<void>
  getCurrentTransfer(): Promise<CurrentTransfer | null>
  confirmTransfer(transfer_id: string): Promise<{ status: 'executed' }>
  cancelTransfer(transfer_id: string): Promise<{ status: 'cancelled' }>
}
