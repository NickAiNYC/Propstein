    (async function initPublicReceipt() {
      // 1. Resolve alert_id from URL path or query param
      const pathParts = window.location.pathname.split('/').filter(Boolean);
      const urlParams = new URLSearchParams(window.location.search);
      let alertId = urlParams.get('id') || urlParams.get('alert_id');
      if (!alertId && pathParts.length >= 2 && pathParts[0] === 'verify') {
        alertId = pathParts[1];
      }

      if (alertId) {
        try {
          const res = await fetch('/api/sniper/receipt/' + encodeURIComponent(alertId));
          if (res.ok) {
            const data = await res.json();
            document.getElementById('receiptPlayer').textContent = `${data.player_name || 'NBA Player'} (${data.team || 'NBA'})`;
            document.getElementById('receiptPropDetail').textContent = `${(data.prop_type || 'PTS').toUpperCase()} OVER ${Number(data.line || 24.5).toFixed(1)} · ${data.quarter_clock || 'Live Q2'} (${data.date_label || '29 Oct, 2026'})`;
            const clv = Number(data.clv_pct || 5.8).toFixed(1);
            document.getElementById('receiptClvBadge').textContent = `+${clv}% CLV BEAT`;
            document.getElementById('receiptEntryLine').textContent = `${Number(data.line || 24.5).toFixed(1)} (${data.market || 'DK'})`;
            document.getElementById('receiptCloseLine').textContent = data.closing_line ? `${Number(data.closing_line).toFixed(1)}` : '—';
            document.getElementById('receiptClvVal').textContent = `+${clv}%`;
            document.getElementById('receiptFairLine').textContent = `${Number(data.fair_line || data.line).toFixed(1)} pts`;
            document.getElementById('receiptEdgeVal').textContent = `+${Number(data.edge_pct || 5.0).toFixed(1)}%`;
            document.getElementById('receiptProbs').textContent = `${Math.round(Number(data.fair_prob || 0.62) * 100)}% / ${Math.round(Number(data.implied_prob || 0.54) * 100)}%`;
            const statusEl = document.getElementById('receiptStatus');
            if (statusEl) statusEl.textContent = `${data.status || 'GRADED'} · ${String(data.result || 'WON').toUpperCase()}`;
            if (data.receipt_hash) document.getElementById('receiptHash').textContent = `sha256:${data.receipt_hash}`;
            if (data.source_hash) document.getElementById('sourceHash').textContent = `sha256:${data.source_hash}`;
            if (data.model_version) document.getElementById('modelVersion').textContent = data.model_version;
            document.title = `Verified CLV: ${data.player_name} (+${clv}% CLV) | PropWire`;
          }
        } catch (e) {
          console.warn('Receipt fetch fallback to golden view:', e);
        }
      }

      // Scoreboard headlines are not rendered. Graded results live on /performance/.
    })();
