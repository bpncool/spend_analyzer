import re
import pandas as pd

PATH_STATEMENT = "data/Acct Statement_XX6061_14032025.txt"

with open(PATH_STATEMENT, mode="r") as f:
    lines = f.readlines()

border_counter = 0
table_indexes = []
for i in range(len(lines)):
    line = lines[i]
    if "-------------" in line:
        border_counter += 1
        if border_counter % 2 == 0:
            table_indexes += [i+1]
    if "**Continue**" in line:
        table_indexes += [i-1]
    if "**********" in line:
        table_indexes += [i-1]
        break

table = []
for i in range(0, len(table_indexes), 2):
    table += lines[table_indexes[i]:table_indexes[i+1]]
    
table_line = []
for line in table:
    if line.strip() == "":
        continue
    elif line[0:7].strip() == "":
        table_line[-1] += line.replace("\n", "")
    if line[0:7].strip() != "":
        table_line += [line]

for i in range(len(table_line)):
    line = table_line[i]
    table_col_1 = line[0:8].strip()
    sale_split = re.split(" |-", line[8:52].strip(), 1)
    # print(len(sale_split))
    table_col_2, table_col_3 = \
        (sale_split[0], sale_split[1]) if len(sale_split) > 1 else ("", sale_split[0])
    other_table_cols = re.sub(r'\s{2,}', '\t', re.sub(r'(?<! ) (?! )', '_', line[53:].replace("\n", "   "))).split("\t")
    table_line[i] = [table_col_1, table_col_2, table_col_3] + other_table_cols
    # print(table_line[i])
    for j in range(7,len(table_line[i])):
        table_line[i][2] += " " + table_line[i][j].replace("_", " ").strip()
    table_line[i] = table_line[i][:7]
    # print(table_line[i])

account_statement = pd.DataFrame(
    table_line,
    columns=["date", "type", "description", "ref_np", "value_date", "withdrawal_or_deposit", "balance"]
)

print(account_statement.head())

account_statement.withdrawal_or_deposit = account_statement.withdrawal_or_deposit \
    .apply(lambda x: x.replace(",", "")) \
    .astype(float)
account_statement.balance = account_statement.balance \
    .apply(lambda x: x.replace(",", "")) \
    .astype(float)
account_statement["value_change"] = account_statement.balance - account_statement.balance.shift(1, fill_value=0)
account_statement["withdrawal"] = account_statement.value_change.apply(lambda x: x if x <= 0 else 0)
account_statement["deposit"] = account_statement.value_change.apply(lambda x: x if x > 0 else 0)
account_statement.withdrawal = account_statement.withdrawal.abs()
account_statement.deposit = account_statement.deposit.abs()
account_statement.to_csv("data/account_statement.csv", index=False)
        

# for line in table_line:
#     print(len(line))
#     # if len(line) == 10:
#     #     print(line)



