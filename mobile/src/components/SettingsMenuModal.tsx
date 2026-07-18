import React from "react";
import { Modal, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import type { SettingsMenuAction, SettingsMenuEntry } from "../lib/settingsMenu";

interface SettingsMenuModalProps {
  visible: boolean;
  title: string;
  subtitle: string;
  entries: SettingsMenuEntry[];
  onSelect: (action: SettingsMenuAction) => void;
  onClose: () => void;
}

/**
 * Server-settings menu as a real bottom sheet (#221) — RN's Android Alert caps at three
 * buttons and silently dropped "Passkey setup" and "Change server" from the old Alert.
 */
export function SettingsMenuModal({ visible, title, subtitle, entries, onSelect, onClose }: SettingsMenuModalProps) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <TouchableOpacity style={styles.backdrop} activeOpacity={1} onPress={onClose}>
        <View style={styles.sheet} onStartShouldSetResponder={() => true}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
          {entries.map((entry) => (
            <TouchableOpacity
              key={entry.action}
              style={styles.row}
              accessibilityRole="button"
              onPress={() => onSelect(entry.action)}
            >
              <Text style={[styles.rowText, entry.destructive && styles.rowTextDestructive]}>{entry.label}</Text>
            </TouchableOpacity>
          ))}
          <TouchableOpacity style={styles.cancel} onPress={onClose} accessibilityRole="button">
            <Text style={styles.cancelText}>Close</Text>
          </TouchableOpacity>
        </View>
      </TouchableOpacity>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center",
    justifyContent: "flex-end",
  },
  sheet: {
    width: "100%",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    backgroundColor: "#1f1f1f",
    padding: 20,
    paddingBottom: 28,
  },
  title: {
    color: "#ffffff",
    fontSize: 18,
    fontWeight: "700",
    textAlign: "center",
  },
  subtitle: {
    color: "#bbbbbb",
    fontSize: 13,
    marginTop: 4,
    marginBottom: 12,
    textAlign: "center",
  },
  row: {
    paddingVertical: 14,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "rgba(255,255,255,0.15)",
  },
  rowText: {
    color: "#ffffff",
    fontSize: 16,
    textAlign: "center",
  },
  rowTextDestructive: {
    color: "#ff6b6b",
  },
  cancel: {
    marginTop: 16,
    paddingVertical: 12,
    borderRadius: 24,
    backgroundColor: "rgba(255,255,255,0.12)",
  },
  cancelText: {
    color: "#ffffff",
    fontSize: 15,
    fontWeight: "600",
    textAlign: "center",
  },
});
