"""Small serial VT screen model for GRUB's cursor-addressed editor output."""
import re


def screen(text, width=80, height=60):
    cells = [[' '] * width for _ in range(height)]
    row = col = 0
    for match in re.finditer(r'\x1b\[([0-?]*)([ -/]*)([@-~])|([^\x1b])', text):
        parameters, intermediate, command, char = match.groups()
        if char is not None:
            if char == '\n':
                row = min(height - 1, row + 1)
            elif char == '\r':
                col = 0
            elif char == '\b':
                col = max(0, col - 1)
            elif char >= ' ':
                cells[row][col] = char
                col = min(width - 1, col + 1)
            continue
        if not re.fullmatch(r'[0-9;]*', parameters):
            continue
        nums = [int(n) if n else 0 for n in parameters.split(';')]
        n = nums[0] or 1
        if command in ('H', 'f'):
            row = min(height - 1, n - 1)
            col = min(width - 1, (nums[1] or 1) - 1 if len(nums) > 1 else 0)
        elif command == 'A': row = max(0, row - n)
        elif command == 'B': row = min(height - 1, row + n)
        elif command == 'C': col = min(width - 1, col + n)
        elif command == 'D': col = max(0, col - n)
        elif command == 'G': col = min(width - 1, n - 1)
        elif command == 'J' and nums[0] == 2:
            cells = [[' '] * width for _ in range(height)]
        elif command == 'K':
            start, end = (0, col + 1) if nums[0] == 1 else ((0, width) if nums[0] == 2 else (col, width))
            cells[row][start:end] = [' '] * (end - start)
    return [''.join(line) for line in cells], row, col


def editor_linux_line(text):
    lines, row, col = screen(text)
    for i, line in enumerate(lines):
        if re.match(r'\s*linux\s', line[2:]):
            combined = line[2:78].rstrip()
            while combined.endswith('\\') and i + 1 < len(lines):
                i += 1
                combined = combined[:-1] + lines[i][2:78].rstrip()
            return combined
    raise ValueError('No linux command in GRUB editor screen')
