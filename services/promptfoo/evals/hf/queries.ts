export const categorySample = `
  SELECT
    question_id,
    question,
    options,
    answer,
    answer_index,
    category
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (PARTITION BY category ORDER BY RANDOM()) AS rn
    FROM test
  )
  WHERE rn <= 1;
`;

export const challengingQuestions = `
  SELECT
    question_id,
    question,
    options,
    answer,
    answer_index,
    category
  FROM test
  WHERE question_id IN (
    7481,
    10529,
    2768,
    6058,
    5610,
    4929,
    8305,
    4359,
    3243,
    1668,
    11981,
    9615,
    5077,
    10505,
    4970,
    7801,
    12240,
    6205,
    9191,
    10720,
    7401,
    8867,
    3039
  )
`