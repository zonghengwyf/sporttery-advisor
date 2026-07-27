import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
    }
    return Promise.reject(err)
  }
)

export default api

// ── Bet record helpers ─────────────────────────────────────────────────────

export interface BetLegIn {
  match_id: number
  home_team: string
  away_team: string
  pick: string
  pick_code: string
  odds: number
}

export interface CreateBetPayload {
  prediction_id?: number | null
  plan_id: string
  legs: BetLegIn[]
  stake: number
  expected_payout?: number
  note?: string
}

export interface BetRecord {
  id: number
  plan_id: string
  legs: Array<{
    match_id?: number
    home_team: string
    away_team: string
    pick: string
    pick_code: string
    odds: number
    actual_result?: string | null
    actual_score?: string | null
    kickoff_at?: string | null
    league?: string | null
  }>
  stake: number
  expected_payout?: number
  effective_odds?: number
  bet_at: string
  status: 'pending' | 'won' | 'lost' | 'void'
  payout?: number | null
  note?: string | null
  prediction_id?: number | null
  profit?: number | null
}

export interface BetSummary {
  total_stake: number
  total_payout: number
  profit: number
  roi: number
  hit_rate: number
  pending_stake: number
  total_bets: number
  settled_bets: number
  won_bets: number
}

export const betsApi = {
  create: (payload: CreateBetPayload) => api.post<BetRecord>('/bets/', payload),
  list: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<BetRecord[]>('/bets/', { params }),
  summary: () => api.get<BetSummary>('/bets/summary'),
  update: (id: number, data: { status?: string; payout?: number; note?: string }) =>
    api.patch<BetRecord>(`/bets/${id}`, data),
  remove: (id: number) => api.delete(`/bets/${id}`),
}
