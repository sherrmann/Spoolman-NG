import React from "react";
import { StyleSheet, Text, TouchableOpacity } from "react-native";

interface FabProps {
  label: string;
  accessibilityLabel: string;
  onPress: () => void;
  small?: boolean;
}

/** Minimal floating action button — no icon library, just a labelled circle. */
export function Fab({ label, accessibilityLabel, onPress, small }: FabProps) {
  return (
    <TouchableOpacity
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      onPress={onPress}
      style={[styles.fab, small && styles.fabSmall]}
      activeOpacity={0.8}
    >
      <Text style={[styles.label, small && styles.labelSmall]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  fab: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: "#dc7734",
    alignItems: "center",
    justifyContent: "center",
    elevation: 4,
    shadowColor: "#000",
    shadowOpacity: 0.3,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
  },
  fabSmall: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "#666666",
  },
  label: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 13,
  },
  labelSmall: {
    fontSize: 15,
  },
});
