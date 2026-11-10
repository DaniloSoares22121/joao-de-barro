/* Token da sessão do João de Barro: uma única chave em localStorage ("jdb_token"),
 * sempre com try/catch (modo anônimo, armazenamento bloqueado). */
const CHAVE = 'jdb_token'

export const token = {
  get: (): string => { try { return localStorage.getItem(CHAVE) || '' } catch { return '' } },
  set: (t: string) => { try { localStorage.setItem(CHAVE, t) } catch { /* modo anônimo */ } },
  limpar: () => { try { localStorage.removeItem(CHAVE) } catch { /* idem */ } },
}
