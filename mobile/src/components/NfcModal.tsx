import React from "react";
import { ActivityIndicator, Modal, StyleSheet, Text, TouchableOpacity, View } from "react-native";

interface NfcModalProps {
  visible: boolean;
  status: string;
  onCancel: () => void;
}

/**
 * Android scan prompt — Android has no system NFC sheet, so the app shows its
 * own. On iOS the Core NFC system sheet appears on top; this modal doubles as
 * the in-app progress state there.
 */
export function NfcModal({ visible, status, onCancel }: NfcModalProps) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <ActivityIndicator size="large" color="#dc7734" />
          <Text style={styles.title}>Scan NFC tag</Text>
          <Text style={styles.status}>{status}</Text>
          <TouchableOpacity style={styles.cancel} onPress={onCancel} accessibilityRole="button">
            <Text style={styles.cancelText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </View>
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
    padding: 28,
    alignItems: "center",
  },
  title: {
    color: "#ffffff",
    fontSize: 18,
    fontWeight: "700",
    marginTop: 16,
  },
  status: {
    color: "#bbbbbb",
    fontSize: 14,
    marginTop: 8,
    textAlign: "center",
  },
  cancel: {
    marginTop: 20,
    paddingVertical: 12,
    paddingHorizontal: 36,
    borderRadius: 24,
    backgroundColor: "rgba(255,255,255,0.12)",
  },
  cancelText: {
    color: "#ffffff",
    fontSize: 15,
    fontWeight: "600",
  },
});
