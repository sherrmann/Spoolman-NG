import { useContext } from "react";
import { ColorModeContext } from "../contexts/color-mode";
import "./spoolIcon.css";

interface Props {
  color?: string | { colors: string[]; vertical: boolean };
  size?: "small" | "large";
  no_margin?: boolean;
}

export default function SpoolIcon(props: Readonly<Props>) {
  let dirClass = "vertical";
  let cols: string[] = [];
  const size = props.size ? props.size : "small";
  const no_margin = props.no_margin ? "no-margin" : "";

  // The default swatch border (#44444430 in spoolIcon.css) is nearly invisible against the dark-mode
  // page background, so a black/dark filament swatch loses its outline (#121). In dark mode override
  // it with a light, semi-transparent border for contrast; light mode keeps the CSS default.
  const { mode } = useContext(ColorModeContext);
  const darkBorderColor = mode === "dark" ? "#ffffff59" : undefined;

  // Fallback when no color is defined: render a neutral placeholder with a
  // question mark. It keeps the exact same footprint/size as a colored icon so
  // the adjacent name text stays aligned with rows that do have a color.
  if (props.color === undefined || props.color === null || props.color === "") {
    return (
      <div className={"spool-icon vertical " + size + " " + no_margin}>
        <div className="spool-icon-unknown" style={darkBorderColor ? { borderColor: darkBorderColor } : undefined}>
          ?
        </div>
      </div>
    );
  }

  if (typeof props.color === "string") {
    cols = [props.color];
  } else {
    dirClass = props.color.vertical ? "vertical" : "horizontal";
    cols = props.color.colors;
  }

  return (
    <div className={"spool-icon " + dirClass + " " + size + " " + no_margin}>
      {cols.map((col) => (
        <div
          key={col}
          style={{
            backgroundColor: "#" + col.replace("#", ""),
            ...(darkBorderColor ? { borderColor: darkBorderColor } : {}),
          }}
        ></div>
      ))}
    </div>
  );
}
