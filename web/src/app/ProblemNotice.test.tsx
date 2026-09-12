import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "../api/errors";
import { ProblemNotice } from "./ProblemNotice";

describe("ProblemNotice (UI-1153 / UI-1156)", () => {
  it("turns a 429 into actionable retry guidance using the server's retry_after_seconds", () => {
    render(
      <ProblemNotice
        error={new ApiError(429, { code: "RATE_LIMITED", detail: "Too many requests", retry_after_seconds: 42, request_id: "r-429" })}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("RATE_LIMITED: Too many requests");
    expect(alert).toHaveTextContent("You can try again in 42 seconds");
    expect(alert).toHaveTextContent("r-429");
  });

  it("shows the request id and violations for a 422 without inventing retry guidance", () => {
    render(
      <ProblemNotice
        error={
          new ApiError(422, {
            code: "VALIDATION_FAILED",
            detail: "Validation failed",
            request_id: "r-422",
            violations: [{ pointer: "/display_name", code: "max_length", message: "at most 160 characters" }],
          })
        }
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("/display_name");
    expect(alert).toHaveTextContent("at most 160 characters");
    expect(alert).toHaveTextContent("r-422");
    expect(alert).not.toHaveTextContent("try again in");
  });

  it("keeps a 500 to its code and request id - never a stack trace", () => {
    render(<ProblemNotice error={new ApiError(500, { code: "INTERNAL_ERROR", detail: "Unexpected error", request_id: "r-500" })} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("INTERNAL_ERROR: Unexpected error");
    expect(alert).toHaveTextContent("r-500");
    expect(alert).not.toHaveTextContent("Traceback");
  });

  it("distinguishes a transport failure from an API refusal", () => {
    render(<ProblemNotice error={new NetworkError(new TypeError("Failed to fetch"))} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The API could not be reached");
  });
});
