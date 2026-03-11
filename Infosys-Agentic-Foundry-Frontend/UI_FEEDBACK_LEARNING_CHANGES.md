# Feedback Learning UI Changes

## Overview
The backend has been updated to change the feedback status from a boolean (`approved: true/false`) to a 3-state string (`status: 'approve' | 'reject' | 'pending'`).

---

## 1. Update API Request Payload

### Endpoint: `PUT /feedback-learning/update/approval-response`

**Before (old payload):**
```json
{
  "response_id": "abc123",
  "lesson": "Some lesson text",
  "approved": true
}
```

**After (new payload):**
```json
{
  "response_id": "abc123",
  "lesson": "Some lesson text",
  "status": "approve"
}
```

### Valid status values:
| Value | Description |
|-------|-------------|
| `approve` | Feedback is approved and will be used during agent inference |
| `reject` | Feedback is rejected and will NOT be used |
| `pending` | Feedback is waiting for review (default state) |

---

## 2. Update API Response Handling

### All feedback list endpoints now return `status` instead of `approved`:

**Before:**
```json
{
  "response_id": "abc123",
  "feedback": "...",
  "approved": true,
  "lesson": "..."
}
```

**After:**
```json
{
  "response_id": "abc123",
  "feedback": "...",
  "status": "approve",
  "lesson": "..."
}
```

---

## 3. Update Status Display Logic

### JavaScript/TypeScript Example:

**Before:**
```javascript
const getStatusLabel = (feedback) => {
  return feedback.approved ? "Approved" : "Pending";
};

const getStatusColor = (feedback) => {
  return feedback.approved ? "green" : "orange";
};
```

**After:**
```javascript
const getStatusLabel = (feedback) => {
  switch (feedback.status) {
    case 'approve':
      return "Approved";
    case 'reject':
      return "Rejected";
    case 'pending':
    default:
      return "Pending";
  }
};

const getStatusColor = (feedback) => {
  switch (feedback.status) {
    case 'approve':
      return "green";
    case 'reject':
      return "red";
    case 'pending':
    default:
      return "orange";
  }
};
```

---

## 4. Update Action Buttons

### Before (Toggle/Single Button):
```jsx
<button onClick={() => updateApproval(feedback.response_id, !feedback.approved)}>
  {feedback.approved ? "Revoke" : "Approve"}
</button>
```

### After (Three Buttons):
```jsx
<div className="action-buttons">
  <button 
    onClick={() => updateStatus(feedback.response_id, 'approve')}
    disabled={feedback.status === 'approve'}
    className="btn-approve"
  >
    Approve
  </button>
  
  <button 
    onClick={() => updateStatus(feedback.response_id, 'reject')}
    disabled={feedback.status === 'reject'}
    className="btn-reject"
  >
    Reject
  </button>
  
  <button 
    onClick={() => updateStatus(feedback.response_id, 'pending')}
    disabled={feedback.status === 'pending'}
    className="btn-pending"
  >
    Pending
  </button>
</div>
```

### Update Handler Function:
```javascript
const updateStatus = async (responseId, newStatus) => {
  await fetch('/feedback-learning/update/approval-response', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      response_id: responseId,
      status: newStatus  // Changed from 'approved' boolean
    })
  });
  // Refresh the list
  fetchFeedbackList();
};
```

---

## 5. Update Statistics Display

### Endpoint: `GET /feedback-learning/get/feedback-stats`

**Before (response):**
```json
{
  "total_feedback": 10,
  "approved_feedback": 5,
  "pending_feedback": 5,
  "agents_with_feedback": 4
}
```

**After (response):**
```json
{
  "total_feedback": 10,
  "approved_feedback": 5,
  "pending_feedback": 3,
  "rejected_feedback": 2,
  "agents_with_feedback": 4
}
```

### Update Stats UI:
```jsx
<div className="stats-container">
  <StatCard label="Total" value={stats.total_feedback} />
  <StatCard label="Approved" value={stats.approved_feedback} color="green" />
  <StatCard label="Pending" value={stats.pending_feedback} color="orange" />
  <StatCard label="Rejected" value={stats.rejected_feedback} color="red" />  {/* NEW */}
  <StatCard label="Agents" value={stats.agents_with_feedback} />
</div>
```

---

## 6. New API Endpoint

A new endpoint is available to get rejected feedback count:

```
GET /feedback-learning/get/rejected-feedback-count

Response:
{
  "rejected_feedback_count": 2
}
```

---

## 7. TypeScript Type Definitions

### Before:
```typescript
interface FeedbackRecord {
  response_id: string;
  query: string;
  feedback: string;
  lesson: string;
  approved: boolean;
  created_at: string;
  department_name: string;
  agent_id: string;
  agent_name: string;
}

interface ApprovalRequest {
  response_id: string;
  lesson?: string;
  approved?: boolean;
}
```

### After:
```typescript
type FeedbackStatus = 'approve' | 'reject' | 'pending';

interface FeedbackRecord {
  response_id: string;
  query: string;
  feedback: string;
  lesson: string;
  status: FeedbackStatus;  // Changed from approved: boolean
  created_at: string;
  department_name: string;
  agent_id: string;
  agent_name: string;
}

interface ApprovalRequest {
  response_id: string;
  lesson?: string;
  status?: FeedbackStatus;  // Changed from approved?: boolean
}

interface FeedbackStats {
  total_feedback: number;
  approved_feedback: number;
  pending_feedback: number;
  rejected_feedback: number;  // NEW
  agents_with_feedback: number;
}
```

---

## 8. CSS Styling Suggestions

```css
.btn-approve {
  background-color: #28a745;
  color: white;
}

.btn-reject {
  background-color: #dc3545;
  color: white;
}

.btn-pending {
  background-color: #ffc107;
  color: black;
}

.status-badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: bold;
}

.status-approve {
  background-color: #d4edda;
  color: #155724;
}

.status-reject {
  background-color: #f8d7da;
  color: #721c24;
}

.status-pending {
  background-color: #fff3cd;
  color: #856404;
}
```

---

## Summary of Changes

| Component | Before | After |
|-----------|--------|-------|
| Field name | `approved` | `status` |
| Data type | `boolean` | `string` |
| Values | `true` / `false` | `'approve'` / `'reject'` / `'pending'` |
| UI States | 2 (Approved/Pending) | 3 (Approved/Rejected/Pending) |
| Stats fields | 4 fields | 5 fields (added `rejected_feedback`) |
