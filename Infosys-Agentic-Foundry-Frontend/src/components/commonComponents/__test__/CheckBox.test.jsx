import { render, fireEvent } from "@testing-library/react";
import CheckBox from "../../../iafComponents/GlobalComponents/CheckBox/CheckBox";

describe("CheckBox", () => {
  it("renders unchecked and toggles on click", () => {
    const handleChange = jest.fn();
    const { getByRole } = render(<CheckBox checked={false} onChange={handleChange} label="Test Checkbox" />);
    const checkbox = getByRole("checkbox");
    expect(checkbox).toHaveAttribute("aria-checked", "false");
    fireEvent.click(checkbox);
    expect(handleChange).toHaveBeenCalledWith(true);
  });

  it("renders checked and toggles off on click", () => {
    const handleChange = jest.fn();
    const { getByRole } = render(<CheckBox checked={true} onChange={handleChange} label="Test Checkbox" />);
    const checkbox = getByRole("checkbox");
    expect(checkbox).toHaveAttribute("aria-checked", "true");
    fireEvent.click(checkbox);
    expect(handleChange).toHaveBeenCalledWith(false);
  });

  it("does not toggle when disabled", () => {
    const handleChange = jest.fn();
    const { getByRole } = render(<CheckBox checked={false} onChange={handleChange} disabled label="Test Checkbox" />);
    const checkbox = getByRole("checkbox");
    expect(checkbox).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(checkbox);
    expect(handleChange).not.toHaveBeenCalled();
  });

  it("toggles on space/enter keydown", () => {
    const handleChange = jest.fn();
    const { getByRole } = render(<CheckBox checked={false} onChange={handleChange} label="Test Checkbox" />);
    const checkbox = getByRole("checkbox");
    fireEvent.keyDown(checkbox, { key: " ", code: "Space" });
    expect(handleChange).toHaveBeenCalledWith(true);
    fireEvent.keyDown(checkbox, { key: "Enter", code: "Enter" });
    expect(handleChange).toHaveBeenCalledWith(true);
  });
});
