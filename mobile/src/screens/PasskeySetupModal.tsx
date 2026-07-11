import React, { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";

import {
  buildAssetlinksJson,
  RELEASED_APK_FINGERPRINT,
  responseWarnings,
  verifyAssetlinks,
  wellKnownUrl,
  type AssetlinksVerdict,
} from "../lib/assetlinks";
import {
  fetchAssetlinks,
  getInstalledFingerprints,
  getInstalledPackageName,
} from "../passkeys/passkeySetup";

interface PasskeySetupModalProps {
  visible: boolean;
  /** Best guess for the RP domain — the detected login portal, else the server host. */
  initialDomain: string | null;
  onClose: () => void;
}

interface CheckResult {
  verdict?: AssetlinksVerdict;
  warnings: string[];
  error?: string;
  checkedUrl: string;
}

/**
 * Guided setup for passkeys: Android only runs WebAuthn ceremonies in the app
 * once the Relying Party's domain vouches for the APK via a Digital Asset
 * Links file. This modal shows the exact file for THIS apk, where to host it,
 * and verifies the hosted copy — turning the platform's "an unknown error has
 * occurred" into a concrete pass/fail.
 */
export function PasskeySetupModal({ visible, initialDomain, onClose }: PasskeySetupModalProps) {
  const [domain, setDomain] = useState(initialDomain ?? "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);

  // The app's identity is fixed per install — compute once per mount.
  const packageName = useMemo(() => getInstalledPackageName() ?? "app.spoolman.companion", []);
  const installedFingerprints = useMemo(() => getInstalledFingerprints(), []);
  const fingerprints = installedFingerprints.length
    ? installedFingerprints
    : [RELEASED_APK_FINGERPRINT];
  const json = buildAssetlinksJson(packageName, fingerprints);

  // Re-prefill when opened for a (possibly newly-detected) portal domain.
  const [seenInitial, setSeenInitial] = useState(initialDomain);
  if (initialDomain !== seenInitial) {
    setSeenInitial(initialDomain);
    if (!domain && initialDomain) {
      setDomain(initialDomain);
    }
  }

  const runCheck = async () => {
    const url = wellKnownUrl(domain);
    if (!url) {
      setResult({
        checkedUrl: "",
        warnings: [],
        error: "Enter the domain to check, e.g. auth.example.com.",
      });
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const fetched = await fetchAssetlinks(url);
      if (fetched.error !== undefined || fetched.payload === undefined) {
        setResult({ checkedUrl: url, warnings: [], error: fetched.error ?? "No response." });
        return;
      }
      setResult({
        checkedUrl: url,
        verdict: verifyAssetlinks(fetched.payload, packageName, installedFingerprints),
        warnings: responseWarnings({
          requestedUrl: url,
          finalUrl: fetched.finalUrl,
          contentType: fetched.contentType,
        }),
      });
    } finally {
      setBusy(false);
    }
  };

  const shareJson = () => {
    Share.share({ message: json }).catch(() => {});
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <ScrollView style={styles.flex} contentContainerStyle={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Passkey setup</Text>
          <TouchableOpacity onPress={onClose} accessibilityRole="button" hitSlop={12}>
            <Text style={styles.close}>Done</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.body}>
          To let this app use passkeys, the domain you sign in on must publicly vouch for it with a
          small file. Without that file, Android shows “an unknown error has occurred” when you tap
          a passkey. Password and code login always work without this.
        </Text>

        <Text style={styles.sectionTitle}>1 · This app’s identity</Text>
        <Text style={styles.body}>Package and signing certificate of the installed APK:</Text>
        <Text style={styles.mono} selectable>
          {packageName}
          {"\n"}
          {fingerprints.join("\n")}
        </Text>
        {installedFingerprints.length === 0 && (
          <Text style={styles.hint}>
            Couldn’t read this APK’s certificate, so the released APK’s fingerprint is shown. If you
            built the app yourself, replace it with yours (the Mobile APK workflow prints it).
          </Text>
        )}

        <Text style={styles.sectionTitle}>2 · Host this file</Text>
        <Text style={styles.body}>
          Serve the JSON below at{" "}
          <Text style={styles.inlineMono}>https://&lt;domain&gt;/.well-known/assetlinks.json</Text>,
          where &lt;domain&gt; is exactly what the address bar shows while you sign in — your login
          portal’s domain (e.g. auth.example.com) if you use one, otherwise the Spoolman domain
          itself. Spoolman servers with this release already serve it on their own domain; a login
          portal’s domain needs it hosted there (see the README for Authelia, Authentik and
          oauth2-proxy examples). It must be reachable without logging in, over HTTPS with a
          publicly-trusted certificate, with no redirect.
        </Text>
        <Text style={styles.mono} selectable>
          {json}
        </Text>
        <TouchableOpacity style={styles.secondaryButton} onPress={shareJson} accessibilityRole="button">
          <Text style={styles.secondaryButtonText}>Share / copy JSON</Text>
        </TouchableOpacity>

        <Text style={styles.sectionTitle}>3 · Check it</Text>
        <Text style={styles.label}>Domain where you sign in</Text>
        <TextInput
          style={styles.input}
          value={domain}
          onChangeText={setDomain}
          placeholder="auth.example.com"
          placeholderTextColor="#888888"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          editable={!busy}
          onSubmitEditing={runCheck}
        />
        <TouchableOpacity
          style={[styles.button, busy && styles.buttonDisabled]}
          onPress={runCheck}
          disabled={busy}
          accessibilityRole="button"
        >
          {busy ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>Check</Text>}
        </TouchableOpacity>

        {result && (
          <View style={styles.resultBox}>
            {result.error !== undefined ? (
              <Text style={styles.fail}>✗ {result.error}</Text>
            ) : result.verdict?.ok ? (
              <Text style={styles.pass}>
                ✓ {result.checkedUrl} vouches for this app. Passkeys should work — if they still
                fail, wait a little (Google caches the check) and make sure your login portal
                supports passkeys.
              </Text>
            ) : (
              result.verdict?.problems.map((problem) => (
                <Text key={problem} style={styles.fail}>
                  ✗ {problem}
                </Text>
              ))
            )}
            {result.warnings.map((warning) => (
              <Text key={warning} style={styles.warn}>
                ⚠ {warning}
              </Text>
            ))}
          </View>
        )}
      </ScrollView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: "#ffffff",
  },
  container: {
    padding: 24,
    paddingBottom: 48,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 12,
  },
  title: {
    fontSize: 22,
    fontWeight: "800",
    color: "#dc7734",
  },
  close: {
    fontSize: 16,
    fontWeight: "700",
    color: "#dc7734",
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: "#333333",
    marginTop: 22,
    marginBottom: 6,
  },
  body: {
    fontSize: 14,
    lineHeight: 20,
    color: "#555555",
  },
  hint: {
    fontSize: 13,
    lineHeight: 18,
    color: "#8c6d1f",
    marginTop: 6,
  },
  mono: {
    fontFamily: "monospace",
    fontSize: 12,
    lineHeight: 17,
    color: "#111111",
    backgroundColor: "#f5f5f5",
    borderRadius: 10,
    padding: 12,
    marginTop: 8,
  },
  inlineMono: {
    fontFamily: "monospace",
    fontSize: 13,
    color: "#111111",
  },
  label: {
    fontSize: 13,
    fontWeight: "600",
    color: "#555555",
    marginTop: 8,
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: "#cccccc",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: "#111111",
    backgroundColor: "#ffffff",
    marginBottom: 12,
  },
  button: {
    backgroundColor: "#dc7734",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  secondaryButton: {
    marginTop: 10,
    paddingVertical: 10,
    alignItems: "center",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#dc7734",
  },
  secondaryButtonText: {
    color: "#dc7734",
    fontSize: 14,
    fontWeight: "700",
  },
  resultBox: {
    marginTop: 16,
    gap: 8,
  },
  pass: {
    color: "#2f7d32",
    fontSize: 14,
    lineHeight: 20,
  },
  fail: {
    color: "#d4380d",
    fontSize: 14,
    lineHeight: 20,
  },
  warn: {
    color: "#8c6d1f",
    fontSize: 14,
    lineHeight: 20,
  },
});
