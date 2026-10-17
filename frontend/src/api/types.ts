// Shapes shared with the backend. Field names match the contract exactly (snake_case).

export type Decision = 'allow' | 'confirm' | 'hold'
export type Kind = 'transfer' | 'bill' | 'withdrawal' | 'deposit'
export type TransferStatus = 'awaiting_yes' | 'held' | 'executed' | 'cancelled'

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
