/**
 * PropStein Live Sniper — SettingsPanel (spec §11 notifications + controls).
 */

export interface SniperSettings {
  evEnterThreshold: number;
  probabilityHaircut: number;
  notifications: {
    onPositiveEv: boolean;
    onPriceImprovement: boolean;
    onQuoteInvalid: boolean;
    onSuspension: boolean;
    onDisconnect: boolean;
    soundEnabled: boolean;
  };
  pauseMonitoring: boolean;
}

export const DEFAULT_SETTINGS: SniperSettings = {
  evEnterThreshold: 0.05,
  probabilityHaircut: 0.02,
  notifications: {
    onPositiveEv: true,
    onPriceImprovement: true,
    onQuoteInvalid: true,
    onSuspension: true,
    onDisconnect: true,
    soundEnabled: false,
  },
  pauseMonitoring: false,
};

export function SettingsPanel({
  settings,
  onChange,
  onClose,
  adapterStatus,
}: {
  settings: SniperSettings;
  onChange: (next: SniperSettings) => void;
  onClose: () => void;
  adapterStatus: Array<{ platform: string; enabled: boolean; note: string }>;
}) {
  const toggle = (key: keyof SniperSettings["notifications"]) => () => {
    onChange({
      ...settings,
      notifications: { ...settings.notifications, [key]: !settings.notifications[key] },
    });
  };
  return (
    <aside className="settings">
      <div className="settings__head">
        <h2>SETTINGS</h2>
        <button type="button" className="btn btn--ghost" onClick={onClose}>CLOSE</button>
      </div>

      <section className="settings__section">
        <h3>ALERT THRESHOLDS</h3>
        <label className="settings__field">
          <span>MINIMUM EV TO ALERT</span>
          <input
            type="number"
            min={0}
            max={0.5}
            step={0.005}
            value={settings.evEnterThreshold}
            onChange={(e) => onChange({ ...settings, evEnterThreshold: Number(e.target.value) })}
          />
          <em>{(settings.evEnterThreshold * 100).toFixed(1)}% per unit staked (post-haircut)</em>
        </label>
        <label className="settings__field">
          <span>UNCERTAINTY HAIRCUT</span>
          <input
            type="number"
            min={0}
            max={0.5}
            step={0.01}
            value={settings.probabilityHaircut}
            onChange={(e) => onChange({ ...settings, probabilityHaircut: Number(e.target.value) })}
          />
          <em>{(settings.probabilityHaircut * 100).toFixed(0)}% shrink of the probability edge before alerting</em>
        </label>
      </section>

      <section className="settings__section">
        <h3>NOTIFICATIONS</h3>
        {(
          [
            ["onPositiveEv", "New positive-EV signal"],
            ["onPriceImprovement", "Meaningful price improvement"],
            ["onQuoteInvalid", "Loss of price validity"],
            ["onSuspension", "Market suspension"],
            ["onDisconnect", "Source or model disconnection"],
            ["soundEnabled", "Play notification sounds"],
          ] as Array<[keyof SniperSettings["notifications"], string]>
        ).map(([key, label]) => (
          <label key={key} className="settings__toggle">
            <input type="checkbox" checked={settings.notifications[key]} onChange={toggle(key)} />
            <span>{label}</span>
          </label>
        ))}
      </section>

      <section className="settings__section">
        <h3>SITE ADAPTERS</h3>
        <ul className="settings__adapters">
          {adapterStatus.map((a) => (
            <li key={a.platform}>
              <span className={`adapter-dot ${a.enabled ? "adapter-dot--on" : ""}`} aria-hidden="true" />
              <span className="adapter-name">{a.platform}</span>
              <span className="adapter-note">{a.note}</span>
            </li>
          ))}
        </ul>
      </section>

      <p className="settings__legal">
        Intelligence only. PropStein never places, submits, modifies, or confirms wagers.
        Betting decisions and actions remain entirely yours. 21+ where legal.
        If gambling is causing harm, call 1-800-GAMBLER.
      </p>
    </aside>
  );
}
